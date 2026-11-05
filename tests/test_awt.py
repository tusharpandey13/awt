import datetime, json, os, shutil, socket, subprocess, sys, tempfile, time, unittest

AWT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "awt"))
GITENV = dict(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e.x", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e.x",
              GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
# built by concatenation so this file never contains a literal secret
AKIA = "AKIA" + "ABCDEFGHIJKLMNOP"


def slurp(path, mode="r"):
    with open(path, mode) as g:
        return g.read()


def ts():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="awt-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "task")
        os.mkdir(self.root)
        self.env = dict(os.environ, HOME=self.tmp, **GITENV)
        self.env.pop("AWT_DIR", None)
        self.env.pop("AWT_BY", None)

    def awt(self, *args, root=None, **kw):
        cmd = [sys.executable, "-I", AWT] + (["--dir", root or self.root] if root != "" else []) + list(args)
        return subprocess.run(cmd, capture_output=True, text=True, env=kw.pop("env", self.env), cwd=kw.pop("cwd", self.tmp), **kw)

    def ok(self, *args, **kw):
        r = self.awt(*args, **kw)
        self.assertEqual(r.returncode, 0, "%s\n%s%s" % (args, r.stdout, r.stderr))
        return r

    def bad(self, *args, code=1, **kw):
        r = self.awt(*args, **kw)
        self.assertEqual(r.returncode, code, "%s\n%s%s" % (args, r.stdout, r.stderr))
        return r

    def init(self, goal=True):
        return self.ok(*(["init", "--goal", "g", "--done", "d"] if goal else ["init"]))

    def p(self, *a):
        return os.path.join(self.root, *a)

    def write(self, rel, text="hello\n"):
        os.makedirs(os.path.dirname(self.p(rel)), exist_ok=True)
        with open(self.p(rel), "w") as g:
            g.write(text)

    def events(self):
        with open(self.p(".awt", "events.jsonl"), "rb") as g:
            return g.read()

    def rows(self, typ=None):
        rs = [json.loads(x) for x in self.events().decode().splitlines() if x.strip().startswith("{")]
        return [r for r in rs if typ is None or r["type"] == typ]

    def raw_append(self, row):
        with open(self.p(".awt", "events.jsonl"), "ab") as g:
            g.write((json.dumps(dict(v=1, ts=ts(), host=socket.gethostname(), by="t", **row)) + "\n").encode())

    def plan(self, *args, target="slack:#eng"):
        r = self.ok("effect", "plan", "--target", target, *args)
        return r.stdout.split()[0]

    def state_of(self, eid):
        for ln in self.ok("effect", "show", eid).stdout.splitlines():
            if ln.startswith("state:"):
                return ln.split(":", 1)[1].strip()


class TestBasics(Base):
    def test_version_isolated_and_block_size(self):
        r = subprocess.run([sys.executable, "-I", AWT, "--version"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("awt", r.stdout)
        self.init()
        with open(self.p("AGENTS.md")) as g:
            txt = g.read()
        self.assertLessEqual(len(txt.encode()), 2048)
        self.assertIn("<!-- awt:begin -->", txt)

    def test_init_twice_changes_nothing(self):
        self.init()
        snap = self.tree()
        self.init(goal=False)
        self.ok("init", "--goal", "g", "--done", "d")
        self.assertEqual(snap, self.tree())

    def tree(self):
        out = {}
        for dp, dns, fns in os.walk(self.root):
            for n in dns + fns:
                p = os.path.join(dp, n)
                out[os.path.relpath(p, self.root)] = slurp(p, "rb") if os.path.isfile(p) else None
        return out

    def test_init_preserves_existing(self):
        self.write("AGENTS.md", "mine\n")
        self.write("README.md", "my readme\n")
        self.write(".claude/settings.json", '{"x": 1}\n')
        self.write(".gitignore", "node_modules")
        r = self.init()
        self.assertEqual(slurp(self.p("README.md")), "my readme\n")
        self.assertEqual(slurp(self.p(".claude", "settings.json")), '{"x": 1}\n')
        self.assertIn("awt resume --hook", r.stdout)  # snippet printed
        ag = slurp(self.p("AGENTS.md"))
        self.assertTrue(ag.startswith("mine\n"))
        self.assertEqual(ag.count("<!-- awt:begin -->"), 1)
        self.assertIn("node_modules\nscratch/", slurp(self.p(".gitignore")))
        self.init(goal=False)
        self.assertEqual(slurp(self.p("AGENTS.md")), ag)

    def test_hook_outside_task(self):
        empty = os.path.join(self.tmp, "nothing")
        os.mkdir(empty)
        r = subprocess.run([sys.executable, "-I", AWT, "resume", "--hook"], capture_output=True, text=True, cwd=empty, env=self.env)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        r = self.bad("note", "x", root="", cwd=empty, code=4)
        self.assertIn("fix: ./awt init", r.stderr)

    def test_json_py_in_task_dir_not_imported(self):
        self.init()
        shutil.copy(AWT, self.p("awt"))
        self.write("json.py", "raise SystemExit(99)\n")
        for flags in ([], ["-S"]):
            r = subprocess.run([sys.executable] + flags + [self.p("awt"), "note", "hi"], capture_output=True, text=True, cwd=self.root, env=self.env)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.rows("note")), 2)
        self.assertFalse(os.path.exists(self.p("__pycache__")))

    def test_records_and_refusals(self):
        self.init()
        self.ok("state", "--now", "a", "--next", "b")
        self.bad("state", "--now", "a", "--next", "b")
        self.ok("state", "--now", "a", "--next", "c")
        self.bad("note", "   ")
        r = self.bad("note", "x" * 281)
        self.assertIn("fix:", r.stderr)
        self.assertIn("docs/", r.stderr)
        self.bad("decide", "x", "--why", "y", "--supersedes", "d-00000000", code=4)  # unknown id is exit 4 per SPEC
        d1 = self.ok("decide", "one", "--why", "w", "--tag", "rule").stdout.split()[0]
        d2 = self.ok("decide", "two", "--why", "w", "--supersedes", d1).stdout.split()[0]
        r = self.bad("decide", "three", "--why", "w", "--supersedes", d1)
        self.assertIn(d2, r.stderr)
        q = self.ok("ask", "why?").stdout.split()[0]
        self.bad("status", "done")
        self.bad("answer", "q-nope", "x", code=4)
        self.ok("answer", q, "because")
        self.bad("answer", q, "again")
        self.ok("status", "done")
        self.ok("status", "paused")
        self.assertIn("two", self.ok("list", "decisions").stdout)
        self.assertNotIn("one", self.ok("list", "decisions").stdout.replace("none", ""))
        self.assertIn("superseded", self.ok("list", "decisions", "--all").stdout)

    def test_ref_kinds(self):
        self.init()
        for tgt, kind in [("https://x.slack.com/archives/C1/p1", "slack"), ("https://a.atlassian.net/wiki/x", "confluence"),
                          ("https://a.atlassian.net/browse/T-1", "jira"), ("ABC-123", "jira"),
                          ("https://github.com/o/r/pull/3", "pr"), ("https://example.com", "link"), ("nonsense", "other")]:
            self.ok("ref", tgt, "--title", "t")
            self.assertEqual(self.rows("ref")[-1]["kind"], kind, tgt)
        repo = os.path.join(self.tmp, "repo")
        subprocess.run(["git", "init", "-q", repo], check=True, env=self.env)
        self.ok("ref", repo, "--title", "r")
        r = self.rows("ref")[-1]
        self.assertEqual((r["kind"], r["path"]), ("repo", repo))
        self.assertIn("branch", r)
        self.ok("ref", "https://x.slack.com/z", "--title", "t", "--no-access")
        self.assertEqual(self.rows("ref")[-1]["access"], "none")

    def test_find_and_list(self):
        self.init()
        self.write("docs/plan.md", "# The Plan\nneedle here\n")
        self.write("scratch/s.md", "needle hidden\n")
        self.write("stuff/x.txt", "other needle\n")
        os.symlink("/etc/hosts", self.p("misc", "lnk"))
        self.ok("note", "a NEEDLE note")
        out = self.ok("find", "needle").stdout
        self.assertIn("docs/plan.md:2:", out)
        self.assertIn("stuff/x.txt:1:", out)
        self.assertIn("event:n-", out)
        self.assertNotIn("scratch", out)
        self.assertEqual(self.ok("find", "zzzzqq").stdout, "")
        lst = self.ok("list").stdout
        self.assertIn("docs/plan.md  The Plan", lst)
        self.assertIn("stuff/x.txt", lst)
        self.assertIn("misc/lnk -> /etc/hosts", lst)

    def test_supersede_and_path_escape(self):
        self.init()
        self.write("docs/a.md", "# a\n")
        self.write("docs/b.md", "# b\n")
        self.write("misc/c.md", "c\n")
        self.bad("supersede", "docs/a.md", "docs/a.md")
        self.bad("supersede", "docs/a.md", "misc/c.md")
        self.bad("supersede", "docs/a.md", "../outside.md")
        self.ok("supersede", "docs/a.md", "docs/b.md")
        self.assertTrue(os.path.exists(self.p("docs", "_superseded", "a.md")))
        self.assertNotIn("_superseded", self.ok("list", "docs").stdout)
        self.assertIn("_superseded", self.ok("list", "docs", "--all").stdout)
        # escape through effect body, plain and via symlink
        outside = os.path.join(self.tmp, "outside.md")
        self.write("../outside.md", "x")
        r = self.bad("effect", "plan", "--target", "t", "--body", outside)
        self.assertIn("escapes", r.stderr)
        os.symlink(outside, self.p("outbox", "ln.md"))
        self.assertIn("escapes", self.bad("effect", "plan", "--target", "t", "--body", "outbox/ln.md").stderr)

    def test_secrets_events_and_capture(self):
        self.init()
        r = self.bad("note", "key is " + AKIA)
        self.assertIn("aws-access-key", r.stderr)
        self.assertNotIn(AKIA, r.stdout + r.stderr)
        self.assertNotIn(AKIA.encode(), self.events())
        self.bad("decide", "c", "--why", "tok " + "ghp_" + "a" * 36)
        body = "chat log\nthe key %s here\n" % AKIA
        r = self.ok("capture", "--from", "slack", "--title", "Chat: Log!", input=body)
        self.assertIn("1 secrets redacted", r.stdout)
        path = r.stdout.split()[0]
        self.assertRegex(path, r"^context/\d{8}-chat-log\.md$")
        txt = slurp(self.p(path))
        self.assertIn("[REDACTED:aws-access-key]", txt)
        self.assertNotIn(AKIA, txt)
        self.assertIn("source: slack", txt)
        r2 = self.ok("capture", "--from", "slack", "--title", "other title", input=body)
        self.assertEqual(r2.stdout.split()[0], path)
        self.assertEqual(len(self.rows("capture")), 1)
        r3 = self.ok("capture", "--from", "slack", "--title", "Chat: Log!", input="different")
        self.assertRegex(r3.stdout.split()[0], r"chat-log-2\.md$")
        self.bad("capture", "--from", "slack", "--title", "t", input="  \n")

    def test_torn_and_garbage_lines(self):
        self.init()
        with open(self.p(".awt", "events.jsonl"), "ab") as g:
            g.write(b"not json at all\n")
            g.write(b'{"v":1,"ts":"x","type":"nope"}\n')
            g.write(b'{"v":1,"ts":"2020","type":"note","id":"n-1"}\n')  # lacks text
            g.write(b'{"v":1,"ts":"2020-01-01T00:00:00.000000Z","type":"no')  # torn tail
        r = self.ok("resume")
        self.assertIn("4 quarantined", r.stdout)
        self.ok("note", "after tear")
        lines = self.events().split(b"\n")
        self.assertEqual(lines[-1], b"")
        self.assertTrue(lines[-2].startswith(b'{"v":1,"ts":"') and b"after tear" in lines[-2])
        self.assertIn("after tear", self.ok("list", "notes").stdout)
        self.assertIn("4 quarantined", self.ok("resume").stdout)  # torn piece stays its own bad line
        self.assertIn("warn 4 quarantined", self.awt("doctor").stdout)

    def test_event_size_cap(self):
        self.init()
        r = self.bad("decide", "c", "--why", "w", "--tag", "t" * 41)
        self.assertIn("fix:", r.stderr)


class TestBrief(Base):
    def test_max_fill_within_budget(self):
        self.init()
        words = "lorem ipsum dolor sit amet consectetur "
        long = lambda n, s="": (s + words * 40)[:n]
        for i in range(25):
            self.ok("state", "--now", long(700, str(i)), "--next", long(300, str(i)), "--scope", "scope-%02d-" % i + "x" * 30)
        for i in range(30):
            self.ok("ask", long(400, str(i)))
        for i in range(25):
            self.ok("decide", long(300, str(i)), "--why", "w", *(["--tag", "rule"] if i % 2 else []))
        for i in range(12):
            self.plan("--run", "true", target="slack:#" + long(150, "c%d" % i).replace(" ", "-"))
        repo = os.path.join(self.tmp, "repo")
        subprocess.run(["git", "init", "-q", repo], check=True, env=self.env)
        self.ok("ref", repo, "--title", "r")
        time.sleep(0.05)
        for i in range(20):
            self.write("misc/file-%02d-%s.txt" % (i, "n" * 60), "x")
        out = self.ok("resume").stdout
        self.assertLessEqual(len(out), 4400)
        self.assertGreater(len(out), 3000)
        self.assertIn("+", out)
        self.assertIn("more: ./awt list questions", out)
        self.assertNotIn("No handoff yet", out)

    def test_no_state_and_hook(self):
        self.init()
        out = self.ok("resume").stdout
        self.assertIn('No handoff yet. Before stopping: ./awt state --now "..." --next "..."', out)
        self.assertIn("Goal: g", out)
        self.assertEqual(self.ok("resume", "--hook").stdout, out)

    def test_changes_since_state(self):
        self.init()
        self.ok("state", "--now", "n", "--next", "x")
        time.sleep(0.05)
        self.write("docs/new.md", "x")
        self.write("scratch/skip.md", "x")
        out = self.ok("resume").stdout
        self.assertIn("docs/new.md", out)
        self.assertNotIn("skip.md", out)
        self.assertIn("1 files newer", out)

    def test_save(self):
        self.init()
        self.bad("save", "m")  # not a git repo
        outer = os.path.join(self.tmp, "outer")
        os.mkdir(outer)
        subprocess.run(["git", "init", "-q", outer], check=True, env=self.env)
        inner = os.path.join(outer, "task")
        os.mkdir(inner)
        self.ok("init", root=inner)
        r = self.bad("save", "m", root=inner)
        self.assertIn("another repo", r.stderr)
        self.assertEqual(subprocess.run(["git", "-C", outer, "log"], capture_output=True, env=self.env).returncode, 128)
        # real repo
        subprocess.run(["git", "init", "-q", self.root], check=True, env=self.env)
        self.write("misc/leak.txt", "key " + AKIA + "\n")
        self.write("docs/ok.md", "fine\n")
        nested = self.p("misc", "sub")
        subprocess.run(["git", "init", "-q", nested], check=True, env=self.env)
        self.write("misc/sub/f.txt", "n")
        r = self.ok("save", "first")
        self.assertIn("saved", r.stdout)
        self.assertIn("leak.txt", r.stderr)
        self.assertIn("nested", r.stderr)
        files = subprocess.run(["git", "-C", self.root, "ls-files"], capture_output=True, text=True, env=self.env).stdout
        self.assertIn("docs/ok.md", files)
        self.assertNotIn("leak.txt", files)
        self.assertNotIn("sub", files)
        self.assertIn("nothing", self.ok("save", "again").stdout)


class TestEffects(Base):
    def setUp(self):
        super().setUp()
        self.init()
        self.hits = self.p("hits.txt")

    def nhits(self):
        return len(slurp(self.hits).split()) if os.path.exists(self.hits) else 0

    def mark(self, eid, to, code=0):
        return self.bad("effect", "mark", eid, to, code=code) if code else self.ok("effect", "mark", eid, to)

    def apply(self, eid, target="slack:#eng", code=0, *extra):
        r = self.awt("effect", "apply", eid, "--target", target, *extra)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r

    def test_manual_flow(self):
        self.write("outbox/m.md", "hello\n")
        r = self.ok("effect", "plan", "--target", "slack:#eng", "--body", "outbox/m.md")
        e = r.stdout.split()[0]
        self.assertIn("effect mark %s sent" % e, r.stdout)
        self.assertEqual(self.state_of(e), "planned")
        self.assertIn("already planned", self.ok("effect", "plan", "--target", "slack:#eng", "--body", "outbox/m.md").stdout)
        self.assertIn("[planned]", self.ok("list", "outbox").stdout)
        self.assertIn("e-", self.apply(e, code=1).stderr)  # manual: refused
        self.mark(e, "not-sent", 1)
        self.mark(e, "sent")
        self.assertEqual(self.state_of(e), "sent")
        for to in ("sent", "not-sent", "dropped"):
            self.mark(e, to, 1)
        self.apply(e, code=1)
        self.assertEqual(len(self.rows("effect")), 2)

    def test_drop_and_replan(self):
        self.write("outbox/m.md", "hello\n")
        e = self.plan("--body", "outbox/m.md")
        self.mark(e, "dropped")
        self.assertEqual(self.state_of(e), "dropped")
        r = self.bad("effect", "plan", "--target", "slack:#eng", "--body", "outbox/m.md")
        self.assertIn("--again", r.stderr)
        self.mark(e, "sent", 1)
        self.mark(e, "not-sent", 1)
        self.apply(e, code=1)
        e2 = self.plan("--body", "outbox/m.md", "--again")
        self.assertNotEqual(e, e2)

    def test_run_flow_sent_and_env(self):
        self.write("outbox/m.md", "hello\n")
        e = self.plan("--body", "outbox/m.md", "--run", 'echo "$AWT_TARGET" >> hits.txt; cat "$AWT_BODY" >> hits.txt')
        self.bad("effect", "mark", e, "sent")
        self.mark(e, "not-sent", 1)
        self.apply(e, "wrong:target", 1)
        self.assertEqual(self.nhits(), 0)
        self.apply(e)
        self.assertEqual(slurp(self.hits).split(), ["slack:#eng", "hello"])
        self.assertEqual(self.state_of(e), "sent")
        self.assertTrue(os.path.exists(self.p(".awt", "runs", e + ".1.log")))
        self.apply(e, code=1)
        self.assertEqual(self.nhits(), 2)
        again = self.ok("effect", "plan", "--target", "slack:#eng", "--body", "outbox/m.md", "--run",
                        'echo "$AWT_TARGET" >> hits.txt; cat "$AWT_BODY" >> hits.txt')
        self.assertIn(e, again.stdout)
        self.assertEqual(len(self.rows("effect")), 3)  # planned, claimed, sent

    def test_failure_goes_unknown_then_retry(self):
        e = self.plan("--run", "echo try >> hits.txt; exit 3")
        self.apply(e, code=1)
        self.assertEqual(self.state_of(e), "unknown")
        self.assertIn(e, self.ok("resume").stdout)
        self.apply(e, code=1)  # never automatic / not planned
        self.assertEqual(self.nhits(), 1)
        r = self.bad("effect", "plan", "--target", "slack:#eng", "--run", "echo other")  # open unknown on target
        self.assertIn("unknown", r.stderr)
        self.mark(e, "dropped", 1)
        self.mark(e, "not-sent")
        self.assertEqual(self.state_of(e), "planned")
        self.assertEqual([r["attempt"] for r in self.rows("effect")][-1], 2)
        self.apply(e, code=1)
        self.assertEqual(self.nhits(), 2)
        self.assertEqual(self.state_of(e), "unknown")
        self.mark(e, "sent")
        self.assertEqual(self.state_of(e), "sent")

    def test_verify_and_timeout(self):
        e = self.plan("--run", "true", "--verify", "exit 1")
        self.apply(e, code=1)
        self.assertEqual(self.state_of(e), "unknown")
        e2 = self.plan("--run", "sleep 30", "--again", target="t2")
        t0 = time.time()
        self.apply(e2, "t2", 1, "--timeout", "1")
        self.assertLess(time.time() - t0, 15)
        self.assertEqual(self.state_of(e2), "unknown")
        e3 = self.plan("--run", "true", "--verify", "true", target="t3")
        self.apply(e3, "t3")

    def test_overwrite_needs_snapshot_and_snapshot_blob(self):
        self.bad("effect", "plan", "--target", "t", "--run", "true", "--class", "overwrite")
        e = self.plan("--run", "true", "--class", "overwrite", "--snapshot", "echo before", target="t")
        self.apply(e, "t")
        self.assertEqual(len(os.listdir(self.p(".awt", "blobs"))), 1)
        e = self.plan("--run", "echo no >> hits.txt", "--class", "overwrite", "--snapshot", "true", target="u")
        self.apply(e, "u", 1)
        self.assertEqual(self.nhits(), 0)
        self.assertEqual(self.state_of(e), "planned")

    def test_after_ordering(self):
        self.bad("effect", "plan", "--target", "t", "--run", "true", "--after", "e-00000000", code=4)
        a = self.plan("--run", "echo a >> hits.txt", target="A")
        b = self.plan("--run", "echo b >> hits.txt", "--after", a, target="B")
        self.apply(b, "B", 1)
        self.apply(a, "A")
        self.apply(b, "B")
        self.assertEqual(slurp(self.hits).split(), ["a", "b"])

    def test_changed_body_refuses(self):
        self.write("outbox/m.md", "v1\n")
        e = self.plan("--body", "outbox/m.md", "--run", "echo sent >> hits.txt")
        self.write("outbox/m.md", "v2\n")
        r = self.apply(e, code=1)
        self.assertIn("plan again", r.stderr)
        self.assertEqual(self.nhits(), 0)
        self.assertEqual(self.state_of(e), "planned")

    def test_again_makes_new_key_and_sends_again(self):
        cmd = "echo sent >> hits.txt"
        e1 = self.plan("--run", cmd)
        self.apply(e1)
        self.assertEqual(self.plan("--run", cmd), e1)
        e2 = self.plan("--run", cmd, "--again")
        self.assertNotEqual(e1, e2)
        k = {r["key"] for r in self.rows("effect") if r["step"] == "planned"}
        self.assertEqual(len(k), 2)
        self.apply(e2)
        self.assertEqual(self.nhits(), 2)

    def test_concurrent_apply_runs_once(self):
        e = self.plan("--run", "echo hit >> hits.txt; sleep 1")
        cmd = [sys.executable, "-I", AWT, "--dir", self.root, "effect", "apply", e, "--target", "slack:#eng"]
        ps = [subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env) for _ in range(6)]
        codes = []
        for p in ps:
            p.communicate()
            codes.append(p.returncode)
        self.assertEqual(sorted(codes), [0] + [1] * 5)
        self.assertEqual(self.nhits(), 1)
        self.assertEqual(self.state_of(e), "sent")
        self.assertEqual(len([r for r in self.rows("effect") if r["step"] == "claimed"]), 1)

    def key_of(self, e):
        return [r for r in self.rows("effect") if r["id"] == e][0]["key"]

    def test_crash_claim_file_without_claimed_row(self):
        e = self.plan("--run", "echo x >> hits.txt")
        open(self.p(".awt", "claims", self.key_of(e) + ".1"), "w").close()
        self.assertEqual(self.state_of(e), "unknown")
        self.assertIn(e, self.ok("resume").stdout)
        self.apply(e, code=1)
        self.assertEqual(self.nhits(), 0)
        self.mark(e, "not-sent")
        self.assertEqual(self.state_of(e), "planned")
        self.apply(e)
        self.assertEqual(self.nhits(), 1)
        e2 = self.plan("--run", "true", "--again", target="other")
        open(self.p(".awt", "claims", self.key_of(e2) + ".1"), "w").close()
        self.mark(e2, "sent")
        self.assertEqual(self.state_of(e2), "sent")

    def test_crash_claimed_row_with_dead_pid(self):
        dead = subprocess.Popen(["true"])
        dead.wait()
        e = self.plan("--run", "echo x >> hits.txt")
        self.raw_append(dict(type="effect", id=e, step="claimed", attempt=1, pid=dead.pid))
        self.assertEqual(self.state_of(e), "unknown")
        self.apply(e, code=1)
        self.assertIn("unknown", self.ok("resume").stdout)
        self.mark(e, "not-sent")
        self.assertEqual(self.state_of(e), "planned")

    def test_claimed_with_live_pid_blocks_marks(self):
        live = subprocess.Popen(["sleep", "30"])
        self.addCleanup(lambda: (live.kill(), live.wait()))
        e = self.plan("--run", "true")
        self.raw_append(dict(type="effect", id=e, step="claimed", attempt=1, pid=live.pid))
        self.assertEqual(self.state_of(e), "claimed")
        for to in ("sent", "not-sent", "dropped"):
            self.mark(e, to, 1)
        self.apply(e, code=1)

    def test_conflict_and_illegal_rows_quarantined(self):
        live = subprocess.Popen(["sleep", "30"])
        self.addCleanup(lambda: (live.kill(), live.wait()))
        e = self.plan("--run", "true")
        self.raw_append(dict(type="effect", id=e, step="claimed", attempt=1, pid=live.pid))
        self.raw_append(dict(type="effect", id=e, step="claimed", attempt=1, pid=live.pid))
        self.assertEqual(self.state_of(e), "conflict")
        self.assertIn("conflict", self.ok("resume").stdout)
        self.mark(e, "sent")
        self.assertEqual(self.state_of(e), "sent")
        self.assertNotIn("quarantined", self.ok("resume").stdout)
        # illegal transitions are skipped and counted
        self.raw_append(dict(type="effect", id=e, step="planned", attempt=2))
        self.raw_append(dict(type="effect", id=e, step="dropped", attempt=1))
        self.raw_append(dict(type="effect", id="e-ffffffff", step="sent", attempt=1))  # unknown id
        self.raw_append(dict(type="effect", id="e-eeeeeeee", step="claimed", attempt=1))
        self.assertEqual(self.state_of(e), "sent")
        self.assertIn("4 quarantined", self.ok("resume").stdout)
        self.bad("effect", "show", "e-ffffffff", code=4)

    def test_illegal_direct_transitions_by_rows(self):
        self.write("outbox/m.md", "x")
        man = self.plan("--body", "outbox/m.md", target="man")
        run = self.plan("--run", "true", target="run")
        self.raw_append(dict(type="effect", id=man, step="claimed", attempt=1, pid=1))  # manual cannot be claimed
        self.raw_append(dict(type="effect", id=run, step="sent", attempt=1))  # planned -> sent needs manual
        self.raw_append(dict(type="effect", id=run, step="unknown", attempt=1))  # planned -> unknown
        self.raw_append(dict(type="effect", id=run, step="planned", attempt=2))  # planned -> planned
        self.assertEqual((self.state_of(man), self.state_of(run)), ("planned", "planned"))
        self.assertIn("4 quarantined", self.ok("resume").stdout)

    def test_status_done_blocked_by_effects(self):
        e = self.plan("--run", "true")
        r = self.bad("status", "done")
        self.assertIn(e, r.stderr)
        self.apply(e)
        self.ok("status", "done")


class SecretPatterns(unittest.TestCase):
    def test_ordinary_hyphenated_words_are_not_secrets(self):
        d = tempfile.mkdtemp(prefix="awt-secret-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        shutil.copy2(AWT, d)
        subprocess.run(["./awt", "init"], cwd=d, capture_output=True)
        for ok in ("disk-encryption-rollout-plan-for-prod", "risk-assessment-review-process-notes"):
            self.assertEqual(subprocess.run(["./awt", "note", ok], cwd=d, capture_output=True).returncode, 0, ok)
        bad = "s" + "k-" + "a" * 24
        self.assertEqual(subprocess.run(["./awt", "note", bad], cwd=d, capture_output=True).returncode, 1)


if __name__ == "__main__":
    unittest.main()
