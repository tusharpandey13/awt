"""End-to-end journeys E-HS1-E-HS15 (docs/e2e-two-host-sync.md): two hosts on one machine, one bare repo, only temp dirs.
Judged on exit codes, stdout and stderr, files and git objects. No network, no real GitHub."""
import datetime, hashlib, http.server, json, os, re, shutil, sqlite3, subprocess, sys, threading, time, unittest, fcntl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synchelp as H
from test_sync import AGE, HAVE_GIT, Hold, mod, old_awt, row, ts
from test_ingest import rec
from test_store import tool_use

T1, T2 = H.H2.TASK, H.H2.TASK2
FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def real_home_digest():
    """U2: the real store and Claude home are not touched."""
    h = hashlib.sha256()
    for base in (os.path.expanduser("~/.local/share/awt-store"), os.path.expanduser("~/.claude/projects")):
        n = 0
        for dp, dns, fns in os.walk(base):
            dns.sort()
            for f in sorted(fns):
                try:
                    st = os.stat(os.path.join(dp, f))
                    h.update(("%s %d %d" % (os.path.join(dp, f), st.st_size, st.st_mtime_ns)).encode())
                    n += 1
                except OSError:
                    pass
            if n > 20000:
                break
    return h.hexdigest()


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class E2E(unittest.TestCase):
    hook = True

    def setUp(self):
        self.h = H.H2()
        self.addCleanup(self.h.cleanup)
        self.h.setup(hook=self.hook)

    # ---- helpers
    def U(self, *rs):
        """U1, U3 after a step."""
        for r in rs:
            self.assertNotIn("Traceback", r.stderr + r.stdout, r.args)
            self.assertIn(r.returncode, (0, 1, 2, 3, 4), r.args)
            if r.returncode == 1 and r.stderr.strip() and "error:" in r.stderr:
                self.assertIn("fix:", r.stderr, r.args)
            self.assertNotRegex(r.stdout + r.stderr, r"://[^/@\s]+@", r.args)
        return rs[0] if len(rs) == 1 else rs

    def ok(self, r):
        self.U(r)
        self.assertEqual(r.returncode, 0, "%s\n%s%s" % (r.args, r.stdout, r.stderr))
        return r

    def awt(self, h, *a, rel=T1, **kw):
        return self.ok(self.h.awt(h, *a, dir=self.h.node(h, rel), **kw))

    def cut(self):
        for r in self.h.cutover():
            self.ok(r)

    def doc(self, h, rel=T1, *a):
        return self.U(self.h.awt(h, "doctor", *a, dir=self.h.node(h, rel)))

    def D(self, h, rel=T1):
        return mod(self.h.node(h, rel)).load()

    def is1(self):
        """IS1: same multiset of lines per node, same listings and masked brief on both hosts."""
        self.assertEqual(self.h.all_lines("A"), self.h.all_lines("B"))
        self.assertTrue(self.h.all_lines("A")[T1])
        for rel in (T1, T2):
            outs = [AGE.sub("AGE", self.h.listing(x, rel)) for x in "AB"]
            self.assertEqual(outs[0], outs[1], rel)
            outs = [AGE.sub("AGE", self.h.awt(x, "resume", dir=self.h.node(x, rel)).stdout) for x in "AB"]
            self.assertEqual(outs[0], outs[1], rel)

    def is4(self):
        self.assertEqual(H.check_is4(self.h.remote, self.h.T), [])

    def last_id(self, r):
        return re.search(r"\b([dqen]-[0-9a-f]{8})\b", r.stdout).group(1)

    # ---- journeys
    def test_e_hs1_bootstrap_and_clean_doctor(self):  # E-HS1: HS12, HS14-HS17, HS30-HS32
        for h in "AB":
            d = self.U(self.h.awt(h, "doctor")).stdout
            self.assertIn("ok git remote origin: declared private sync remote", d)
            for bad in ("does not ignore", "not merged as union", "pre-commit hook", "visibility"):
                self.assertNotIn(bad, d, h)
        r = self.ok(self.h.sync("B"))
        self.assertEqual(r.stdout.strip(), "synced %s: committed 0 files, merged 0 commits, no push" % self.h.tree("B"))
        self.is1()

    def test_e_hs2_disjoint_nodes(self):  # E-HS2: HS4, HS12 (homelab AT-03)
        self.cut()
        for rel, h in ((T1, "A"), (T2, "B")):
            self.awt(h, "note", "n of " + h, rel=rel)
            self.awt(h, "state", "--now", "now " + h, "--next", "next", rel=rel)
            d = self.awt(h, "decide", "choice " + h, "--why", "w", rel=rel)
            self.awt(h, "ask", "question from " + h, rel=rel)
        self.cut()
        for h in "AB":
            for rel in (T1, T2):
                self.assertIn("ok 0 quarantined rows", self.doc(h, rel).stdout)
        self.is1()
        self.is4()
        for rel, h in ((T1, "A"), (T2, "B")):
            self.assertIn("now " + h, self.h.awt("B" if h == "A" else "A", "resume", dir=self.h.node("B" if h == "A" else "A", rel)).stdout)

    def test_e_hs3_same_node_interleaved_clocks(self):  # E-HS3: HS2, HS3, HS4, HS8 (homelab AT-04)
        self.cut()
        self.h.skew["B"] = 5
        effs = []
        for i in range(20):
            for h in "AB":
                self.awt(h, "state", "--now", "%s%d" % (h.lower(), i), "--next", "n")
                self.awt(h, "note", "%s note %d" % (h, i))
            if i < 3:
                for h in "AB":
                    eid = self.last_id(self.awt(h, "effect", "plan", "--target", "slack:#%s%d" % (h.lower(), i)))
                    self.awt(h, "effect", "begin", eid)
                    self.awt(h, "effect", "mark", eid, "sent", "--ref", "r-" + eid)
                    effs.append(eid)
        self.cut()
        for h in "AB":
            D = self.D(h)
            self.assertEqual(D["states"]["main"]["now"], "b19", h)  # B's clock is ahead
            self.assertEqual(D["bad"], 0)
            self.assertEqual(D["dups"], 0)
            self.assertEqual({D["eff"][e]["state"] for e in effs}, {"sent"})
            allst = json.loads(self.h.awt(h, "list", "state", "--all", "--json", dir=self.h.node(h, T1)).stdout)
            nows = [x["now"] for x in allst]
            self.assertEqual(len([n for n in nows if re.fullmatch(r"[ab]\d+", n)]), 40)
        self.is1()
        self.is4()
        self.assertEqual(len(re.findall(r"\bb19\b", self.h.awt("A", "resume", dir=self.h.node("A", T1)).stdout)) > 0, True)

    def test_e_hs4_causality_under_skew(self):  # E-HS4: HS2, HS9
        self.cut()
        self.h.skew["B"] = -3600
        self.awt("A", "state", "--now", "A1", "--next", "n")
        self.cut()
        a1 = [r for r in self.D("A")["rows"] if r["type"] == "state"][-1]["ts"]
        self.awt("B", "state", "--now", "B1", "--next", "n")
        self.cut()
        for h in "AB":
            D = self.D(h)
            self.assertEqual(D["states"]["main"]["now"], "B1", h)
            b1 = D["states"]["main"]["ts"]
            self.assertEqual(datetime.datetime.strptime(b1, FMT) - datetime.datetime.strptime(a1, FMT), datetime.timedelta(microseconds=1))
        d = self.doc("B").stdout
        m = re.search(r"rows up to (\d+) s ahead of this clock \(host host-a\)", d)
        self.assertTrue(m, d)
        self.assertLessEqual(abs(int(m.group(1)) - 3600), 5)
        self.assertNotRegex(self.h.awt("B", "resume", dir=self.h.node("B", T1)).stdout, r"-\d+[smhd] ago")
        # again with A's clock two hours ahead
        self.h.skew.update(A=7200, B=0)
        self.awt("A", "state", "--now", "A2", "--next", "n")
        self.cut()
        self.awt("B", "state", "--now", "B2", "--next", "n")
        self.cut()
        for h in "AB":
            self.assertEqual(self.D(h)["states"]["main"]["now"], "B2", h)
        self.is1()

    def test_e_hs5_effects_across_hosts(self):  # E-HS5: HS8
        self.cut()
        eid = self.last_id(self.awt("A", "effect", "plan", "--target", "slack:#one"))
        self.awt("A", "effect", "begin", eid)
        self.cut()
        self.awt("B", "effect", "mark", eid, "sent", "--ref", "r1")
        self.cut()
        for h in "AB":
            D = self.D(h)
            self.assertEqual((D["eff"][eid]["state"], D["bad"]), ("sent", 0))
        e2 = self.last_id(self.awt("A", "effect", "plan", "--target", "slack:#two"))
        self.cut()
        self.awt("A", "effect", "begin", e2)
        self.awt("B", "effect", "begin", e2)
        self.cut()
        bad = []
        for h in "AB":
            D = self.D(h)
            self.assertEqual(D["bad"], 1, h)
            self.assertEqual([x[0] for x in D["xbegun"]], [e2])
            bad.append(sorted(r["ts"] for r in D["eff"][e2]["hist"]))
            self.assertIn("warn effect %s: begun on host-a and host-b (attempt 1)" % e2, self.doc(h).stdout)
        self.assertEqual(bad[0], bad[1])  # the same row survives on both

    def test_e_hs6_concurrent_supersede_and_answer(self):  # E-HS6: HS8
        d1 = self.last_id(self.awt("A", "decide", "base", "--why", "w"))
        q1 = self.last_id(self.awt("A", "ask", "which?"))
        self.cut()
        self.awt("A", "decide", "X", "--why", "w", "--supersedes", d1)
        self.awt("B", "decide", "Y", "--why", "w", "--supersedes", d1)
        self.awt("A", "answer", q1, "from a")
        self.awt("B", "answer", q1, "from b")
        self.cut()
        warns = []
        for h in "AB":
            D = self.D(h)
            self.assertEqual({x["choice"] for x in D["cur_dec"]}, {"X", "Y"})
            first = sorted((r["ts"], r["host"]) for r in D["rows"] if r["type"] == "answer")[0]
            self.assertEqual(D["ans"][q1]["host"], first[1])
            d = self.doc(h).stdout
            warns.append([ln for ln in d.splitlines() if "superseded by two rows" in ln or "answered twice" in ln])
        self.assertEqual(len(warns[0]), 2)
        self.assertEqual(warns[0], warns[1])

    def test_e_hs7_legacy_needs_no_migration(self):  # E-HS7: HS5, IS6
        old = old_awt(self.h.T)
        if not old:
            self.skipTest("no v0.4.1 tag in this clone")
        h2 = H.H2()
        self.addCleanup(h2.cleanup)
        A = h2.tree("A")
        os.makedirs(A)

        def o(*a, dir=None):
            r = subprocess.run([sys.executable, "-I", old] + (["--dir", dir] if dir else []) + list(a), capture_output=True, text=True, env=h2.env("A"), cwd=A)
            self.assertEqual(r.returncode, 0, "%s\n%s%s" % (a, r.stdout, r.stderr))
            return r
        o("init", "--kind", "root", "--name", "tree")
        for p in ("parsekit", "ledgerline"):
            o("init", "--kind", "project", "--name", p)
            o("init", "--kind", "workspace", "--name", "main", dir=h2.node("A", "projects/" + p))
            o("init", "--kind", "task", "--name", "work", "--goal", "Ship " + p, "--done", "Merged", dir=h2.node("A", "projects/%s/workspaces/main" % p))
        t = h2.node("A", T1)
        o("note", "legacy note", dir=t)
        o("state", "--now", "legacy now", "--next", "legacy next", dir=t)
        d = re.search(r"(d-[0-9a-f]{8})", o("decide", "old", "--why", "w", dir=t).stdout).group(1)
        o("decide", "newer", "--why", "w", "--supersedes", d, dir=t)
        os.makedirs(os.path.join(t, "outbox"), exist_ok=True)
        open(os.path.join(t, "outbox", "b.md"), "w").write("body\n")
        eid = re.search(r"(e-[0-9a-f]{8})", o("effect", "plan", "--target", "slack:#eng", "--body", "outbox/b.md", dir=t).stdout).group(1)
        o("effect", "begin", eid, dir=t)
        o("effect", "mark", eid, "sent", "--ref", "https://example.invalid/s", dir=t)
        o("init", "--child", "run-1", dir=t)

        def outs(awt):
            res = []
            for rel in (T1, T1 + "/agents/run-1", "projects/ledgerline/workspaces/main/tasks/work"):
                for args in (["resume"], ["list", "notes", "--all", "--json"], ["list", "decisions", "--all", "--json"], ["list", "effects", "--all", "--json"], ["doctor"]):
                    r = subprocess.run([sys.executable, "-I", awt, "--dir", h2.node("A", rel)] + args, capture_output=True, text=True, env=h2.env("A"))
                    res.append(AGE.sub("AGE", re.sub(r"/awt-hs-\w+", "", r.stdout)))
            return res
        before = h2.all_lines("A")
        a, b = outs(old), outs(H.AWT)
        self.assertEqual(a, b)  # IS6
        self.assertEqual(before, h2.all_lines("A"))  # no file changed
        # make it the tree of H2: git, attributes, hook, remote; write new rows on both hosts
        self.assertEqual(h2.git("A", "init", "-q").returncode, 0)
        open(os.path.join(A, ".gitattributes"), "w").write("events.jsonl merge=union\n")
        h2.install_hook("A")
        self.assertEqual(h2.awt("A", "ref", h2.remote, "--kind", "sync", "--title", "private sync remote").returncode, 0)
        for c in (["remote", "add", "origin", h2.remote], ["add", "-A"], ["commit", "-q", "-m", "legacy"], ["push", "-q", "origin", "HEAD:main"]):
            self.assertEqual(h2.git("A", *c).returncode, 0)
        self.assertEqual(H.run(["git", "clone", "-q", h2.remote, h2.tree("B")], env=H.clean_env(h2.T, h2.T)).returncode, 0)
        h2.install_hook("B")
        for x, w in (("A", "from a"), ("B", "from b")):
            self.assertEqual(h2.awt(x, "note", w, dir=h2.node(x, T1)).returncode, 0)
        for r in h2.cutover():
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(h2.all_lines("A"), h2.all_lines("B"))
        legacy = [json.loads(x) for x in before[T1]]
        got = mod(h2.node("B", T1)).load()["rows"]
        self.assertEqual([r for r in got if r.get("v") == 1], [r for r in got[:len(legacy)]])
        self.assertTrue(all(r.get("v") == 2 for r in got[len(legacy):]))
        self.assertEqual({r["text"] for r in got if r["type"] == "note"}, {"legacy note", "from a", "from b"})

    def test_e_hs8_the_commit_check(self):  # E-HS8: HS20-HS24
        self.cut()
        led = os.path.join(self.h.node("A", T1), ".awt", "events.jsonl")
        with open(led, "ab") as g:
            g.write(b'{"v":2,"ts":"2026')
        remote_before = self.h.git_T("--git-dir", self.h.remote, "rev-parse", "main").stdout
        self.assertEqual(self.h.git("A", "add", "-A").returncode, 0)
        r = self.h.git("A", "commit", "-q", "-m", "x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("torn tail", r.stderr + r.stdout)
        self.assertEqual(self.h.git_T("--git-dir", self.h.remote, "rev-parse", "main").stdout, remote_before)
        self.h.git("A", "reset", "-q")
        self.ok(self.h.sync("A"))
        self.assertTrue(open(led, "rb").read().endswith(b"\n"))
        self.assertIn("1 quarantined", self.doc("A").stdout)
        self.assertNotEqual(self.h.git_T("--git-dir", self.h.remote, "rev-parse", "main").stdout, remote_before)
        # a changed byte in a committed row
        data = open(led, "rb").read()
        i = data.index(b'"goal"') + 9
        open(led, "wb").write(data[:i] + b"Z" + data[i + 1:])
        self.h.git("A", "add", "-A")
        r = self.h.git("A", "commit", "-q", "-m", "tamper")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("changed or removed since HEAD", r.stderr + r.stdout)
        open(led, "wb").write(data)
        self.h.git("A", "reset", "-q")
        with open(led, "ab") as g:
            g.write(b"=======\n")
        self.h.git("A", "add", "-A")
        r = self.h.git("A", "commit", "-q", "-m", "markers")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("conflict markers", r.stderr + r.stdout)
        self.is4()

    def test_e_hs9_remotes(self):  # E-HS9: HS30-HS34
        seen = []
        status = [200]

        class Stub(http.server.BaseHTTPRequestHandler):
            def do_HEAD(s):
                seen.append((s.path, {k.lower(): v for k, v in s.headers.items()}))
                s.send_response(status[0])
                s.end_headers()

            def log_message(s, *a):
                pass
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stub)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        env = {"AWT_TEST_GITHUB_BASE": "http://127.0.0.1:%d" % srv.server_address[1]}

        def doctor():
            return self.U(self.h.awt("A", "doctor", over=env))
        self.assertEqual(self.h.git("A", "remote", "add", "extra", "git@github.com:parsekit-bot/other.git").returncode, 0)
        d = doctor().stdout
        self.assertIn("warn git remote extra: not declared", d)
        self.assertEqual(self.h.awt("A", "ref", "https://github.com/parsekit-bot/other", "--kind", "sync", "--title", "x").returncode, 0)
        r = doctor()
        self.assertIn("ok git remote extra: declared private sync remote", r.stdout)
        self.assertEqual(r.returncode, 1)  # stub says 200: public
        self.assertIn("fail git remote extra is public", r.stdout)
        status[0] = 404
        r = doctor()
        self.assertNotIn("extra is public", r.stdout)
        self.assertNotIn("visibility", r.stdout)
        status[0] = 503
        self.assertIn("warn git remote extra: visibility not checked (HTTP 503)", doctor().stdout)
        srv.shutdown()
        srv.server_close()
        self.assertIn("visibility not checked (OFFLINE)", doctor().stdout)
        self.assertEqual(self.h.awt("A", "ref", "https://github.com/parsekit-bot/other", "--kind", "link", "--title", "withdrawn").returncode, 0)
        self.assertIn("warn git remote extra: not declared", doctor().stdout)
        n = len(seen)
        self.assertEqual(self.U(self.h.awt("A", "doctor", "--staged")).returncode, 0)
        self.assertEqual(len(seen), n)
        for _, hd in seen:
            self.assertFalse({"authorization", "cookie"} & set(hd))

    def claude_session(self, h, sid, cwd, cmds, word):
        proj = os.path.join(self.h.T, h, "home", ".claude", "projects", "-work-" + sid[:6])
        os.makedirs(proj, exist_ok=True)
        base = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        with open(os.path.join(proj, sid + ".jsonl"), "w") as g:
            for i, c in enumerate([None] + cmds):
                r = rec("user", 0, "please look at %s" % word) if c is None else tool_use(i, "t%d" % i, "Bash", {"command": c})
                r.update(sessionId=sid, cwd=cwd, timestamp=(base + datetime.timedelta(seconds=5 * i)).strftime("%Y-%m-%dT%H:%M:%S.000Z"), uuid="%s-%d" % (sid[:4], i),
                         parentUuid="%s-%d" % (sid[:4], i - 1) if i else None)
                g.write(json.dumps(r) + "\n")

    def repos(self, host_b_has_ledgerline=False):
        for name, files in (("parsekit", ("Cargo.toml", "a.rs", "b.rs")), ("ledgerline", ("package.json",))):
            d = os.path.join(self.h.T, "repos", name)
            os.makedirs(d, exist_ok=True)
            for f in files:
                open(os.path.join(d, f), "w").write("x\n")
            subprocess.run(["git", "init", "-q", d], env=H.clean_env(self.h.T, self.h.T), check=True)
            subprocess.run(["git", "-C", d, "add", "-A"], env=H.clean_env(self.h.T, self.h.T), check=True)
            subprocess.run(["git", "-C", d, "commit", "-q", "-m", "i"], env=H.clean_env(self.h.T, self.h.T), check=True)
        return os.path.join(self.h.T, "repos", "parsekit"), os.path.join(self.h.T, "repos", "ledgerline")

    def s2(self):
        pk, ll = self.repos()
        self.claude_session("A", "aaaa0000-0000-4000-8000-00000000000a", pk, ["cargo test", "cargo test --all", "cargo build", "adb devices", "ffmpeg -i x y", "cargo test x", "cargo test y"], "alphaword")
        self.claude_session("B", "bbbb0000-0000-4000-8000-00000000000b", ll, ["adb devices", "ffmpeg -i x y", "ls"], "betaword")
        for h in "AB":
            self.ok(self.h.awt(h, "ingest"))
        return pk, ll

    def test_e_hs10_store_after_pull_and_rsync(self):  # E-HS10: HS40-HS43 (homelab AT-09, AW-9, AW-10)
        self.s2()
        H.rsync(os.path.join(self.h.T, "A", "store"), os.path.join(self.h.T, "B", "store"))
        H.rsync(os.path.join(self.h.T, "B", "store"), os.path.join(self.h.T, "A", "store"))
        self.awt("A", "note", "tree note from a")
        self.cut()
        for h in "AB":
            r = self.ok(self.h.awt(h, "ingest"))
            hits = self.ok(self.h.awt(h, "find", "--sessions", "betaword" if h == "A" else "alphaword"))
            self.assertTrue(hits.stdout.strip(), h)
            db = os.path.join(self.h.T, h, "store", "store.db")
            c = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
            self.assertEqual(c.execute("select count(*) from sessions").fetchone()[0], 2)
            self.assertEqual(c.execute("select count(*) from records where fields like '%tree note from a%'").fetchone()[0], 1)
            c.close()
            dump = H.logical(db)
            self.ok(self.h.awt(h, "ingest", "--rebuild"))  # IS5
            self.assertEqual(H.logical(db), dump, h)
            before = open(db, "rb").read()
            r = self.ok(self.h.awt(h, "ingest"))
            self.assertIn("ingested 0 rows", r.stdout)
            self.assertEqual(open(db, "rb").read(), before)

    def test_e_hs11_profiles_on_two_hosts(self):  # E-HS11: HS50-HS57
        pk, ll = self.s2()
        # B has no ledgerline repo: the same sessions, with the repo path missing on B
        H.rsync(os.path.join(self.h.T, "A", "store"), os.path.join(self.h.T, "B", "store"))
        shutil.move(ll, ll + ".gone")
        self.cut()
        for h in "AB":
            self.ok(self.h.awt(h, "ingest"))
        docs = {h: json.load(open(os.path.join(self.h.T, h, "store", "views", "profiles.json"))) for h in "AB"}
        self.assertEqual((docs["A"]["repos"][pk]["class"], docs["A"]["repos"][pk]["source"]), ("build-heavy", "observed"))
        self.assertNotIn(ll, docs["B"]["repos"])
        for h in "AB":
            self.assertEqual(oct(os.stat(os.path.join(self.h.T, h, "store", "views", "profiles.json")).st_mode & 0o777), "0o600")
            raw = open(os.path.join(self.h.T, h, "store", "views", "profiles.json")).read()
            for arg in ("--all", "x y", "-i"):
                self.assertNotIn(arg, raw)
        proj = "projects/ledgerline"
        self.awt("B", "decide", "ledgerline is media work", "--why", "x", "--tag", "profile:media-device", rel=proj)
        self.cut()
        for h in "AB":
            self.ok(self.h.awt(h, "ingest"))
            doc = json.load(open(os.path.join(self.h.T, h, "store", "views", "profiles.json")))
            self.assertIn(("media-device", "override"), [(p["class"], p["source"]) for p in doc["projects"].values()], h)

    def test_e_hs12_sync_in_flight(self):  # E-HS12: HS10, HS11, HS13
        top = os.path.join(self.h.tree("A"), ".awt")
        hold = Hold(top)
        threading.Timer(3, hold.release).start()
        t0 = time.time()
        r = self.U(self.h.awt("A", "note", "waits", dir=self.h.node("A", T1), over={"AWT_TEST_SYNC_WAIT_S": "6"}))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertGreaterEqual(time.time() - t0, 2.5)
        hold = Hold(top)
        t0 = time.time()
        r = self.U(self.h.awt("A", "resume", "--hook", dir=self.h.node("A", T1), over={"AWT_TEST_SYNC_WAIT_S": "5"}))
        self.assertEqual(r.returncode, 0)
        self.assertLess(time.time() - t0, 2.5)
        r = self.U(self.h.awt("A", "note", "y", dir=self.h.node("A", T1), over={"AWT_TEST_SYNC_WAIT_S": "1"}))
        self.assertEqual(r.returncode, 1)
        self.assertIn("a sync of %s is in progress" % self.h.tree("A"), r.stderr)
        self.assertIn("fix: rerun in a few seconds", r.stderr)
        hold.release()
        # a writer that opened the ledger before a git merge ran under the lock keeps its row
        self.awt("B", "note", "from b")
        self.ok(self.h.sync("B"))
        stop = threading.Event()
        errs = []

        def writer():
            i = 0
            while not stop.is_set():
                r = self.h.awt("A", "note", "w%d" % i, dir=self.h.node("A", T1), over={"AWT_TEST_SYNC_WAIT_S": "20"})
                if r.returncode == 0:
                    errs.append("w%d" % i)
                i += 1
        th = threading.Thread(target=writer)
        th.start()
        for _ in range(3):
            self.ok(self.h.sync("A"))
        stop.set()
        th.join()
        self.ok(self.h.sync("A"))
        texts = {n["text"] for n in self.D("A")["notes"]}
        self.assertTrue(set(errs) <= texts, set(errs) - texts)
        self.assertIn("from b", texts)

    def test_e_hs13_conflicting_push(self):  # E-HS13: HS12, IS7
        self.awt("A", "note", "a1")
        self.awt("B", "note", "b1")
        self.ok(self.h.sync("A"))
        r = self.ok(self.h.sync("B"))
        self.assertIn("merged 1 commits, pushed", r.stdout)
        # B's push loses a race: a pre-receive hook that rejects the first push
        hook = os.path.join(self.h.remote, "hooks", "pre-receive")
        flag = os.path.join(self.h.T, "reject-once")
        open(flag, "w").write("x")
        open(hook, "w").write("#!/bin/sh\nif [ -e %s ]; then rm -f %s; echo 'non-fast-forward (test)' >&2; exit 1; fi\n" % (flag, flag))
        os.chmod(hook, 0o755)
        self.awt("B", "note", "b2")
        r = self.ok(self.h.sync("B"))
        self.assertIn("push rejected", r.stdout)
        self.ok(self.h.sync("B"))
        self.cut()
        self.is1()
        self.is4()
        self.assertTrue({"a1", "b1", "b2"} <= {n["text"] for n in self.D("A")["notes"]})

    def test_e_hs14_older_awt_on_one_host(self):  # E-HS14: HS6 (homelab AT-02)
        old = old_awt(self.h.T)
        if not old:
            self.skipTest("no v0.4.1 tag in this clone")
        self.awt("A", "note", "a v2 row")
        self.cut()
        for i in range(3):
            r = subprocess.run([sys.executable, "-I", old, "--dir", self.h.node("B", T1), "note", "old %d" % i], capture_output=True, text=True, env=self.h.env("B"))
            self.assertEqual(r.returncode, 0, r.stderr)
        self.cut()
        for h in "AB":
            D = self.D(h)
            self.assertEqual(D["bad"], 0)
            kinds = [r.get("v") for r in D["rows"]]
            self.assertEqual(kinds, sorted(kinds, key=lambda v: v == 2))  # every v1 row before every v2 row
            self.assertEqual(len(D["v1_late"]), 3)
            self.assertRegex(self.doc(h).stdout, r"warn 3 v1 rows after v2 rows \(lines \d+, \d+, \d+\): a host runs an older awt")

    def test_e_hs15_full_disk(self):  # E-HS15: HS21, HS25, HS45
        self.cut()
        r = self.U(self.h.awt("A", "note", "x", dir=self.h.node("A", T1), over={"AWT_TEST_SHORT_WRITE": "10"}))
        self.assertEqual(r.returncode, 1)
        self.assertIn("short write", r.stderr)
        self.assertIn("fix:", r.stderr)
        self.ok(self.h.sync("A"))
        self.is4()
        led = os.path.join(self.h.node("A", T1), ".awt", "events.jsonl")
        data = open(led, "rb").read()
        open(led, "wb").write(data[:len(data) // 2])
        d = self.doc("A")
        self.assertEqual(d.returncode, 1)
        self.assertIn("fail ledger is not an extension of the committed one (rows lost?)", d.stdout)
        self.assertEqual(self.h.git("A", "checkout", "--", ".").returncode, 0)
        self.assertNotIn("not an extension", self.doc("A").stdout)
        self.ok(self.h.awt("A", "ingest"))
        db = os.path.join(self.h.T, "A", "store", "store.db")
        before = (open(db, "rb").read() if os.path.exists(db) else None, self.h.all_lines("A"))
        r = self.U(self.h.awt("A", "ingest", "--rebuild", over={"AWT_TEST_FREE_BYTES": "1"}))
        self.assertEqual(r.returncode, 1)
        self.assertIn("fix:", r.stderr)
        self.assertEqual((open(db, "rb").read() if os.path.exists(db) else None, self.h.all_lines("A")), before)


if __name__ == "__main__":
    unittest.main()
