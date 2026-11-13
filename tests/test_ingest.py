"""awt ingest --source claude: canonical raw JSONL store. Fixtures are a fictional `parsekit` project."""
import hashlib, importlib.machinery, importlib.util, json, os, stat, subprocess, sys, time, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_awt import AWT, Base, slurp

# token-shaped strings are built at run time so this file holds no literal secret
GH = "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0" * 2
AKIA = "AKIA" + "ABCDEFGHIJKLMNOP"
SID = "3f0c1a2b-0000-4000-8000-00000000aaaa"
CWD = "/work/parsekit"


def rec(kind, i, text=None, **kw):
    r = {"type": kind, "uuid": "u-%d" % i, "parentUuid": "u-%d" % (i - 1) if i else None, "sessionId": SID,
         "timestamp": "2026-10-%02dT09:%02d:00.000Z" % (3 + i // 50, i % 50), "cwd": CWD}
    if kind == "user":
        r["message"] = {"role": "user", "content": text}
    elif kind == "assistant":
        r["message"] = {"role": "assistant", "content": [{"type": "text", "text": text}], "usage": {"input_tokens": 5, "output_tokens": 7}}
    r.update(kw)
    return r


def line(r):
    return (json.dumps(r) + "\n").encode()


class Ing(Base):
    def setUp(self):
        super().setUp()
        self.store = os.path.join(self.tmp, "store")
        self.proj = os.path.join(self.tmp, "claude", "projects")
        self.pdir = os.path.join(self.proj, "-work-parsekit")
        os.makedirs(self.pdir)
        self.env.update(AWT_STORE=self.store, AWT_CLAUDE_PROJECTS=self.proj, AWT_CLAUDE_SETTINGS=os.path.join(self.tmp, "claude", "settings.json"))

    def src(self, sid=SID, sub=None):
        return os.path.join(self.pdir, sid + ".jsonl") if not sub else os.path.join(self.pdir, SID, "subagents", sub + ".jsonl")

    def put(self, rows, path=None, mode="wb"):
        path = path or self.src()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode) as g:
            for r in rows:
                g.write(r if isinstance(r, bytes) else line(r))
        return path

    def base_rows(self):
        return [{"type": "summary", "summary": "parsekit tokenizer", "leafUuid": "u-0"},
                rec("user", 0, "add a tokenizer to parsekit"),
                rec("assistant", 1, "reading lexer.py"),
                rec("user", 2, [{"type": "tool_result", "tool_use_id": "t1", "content": "def lex(): pass"}]),
                rec("assistant", 3, "done")]

    def ingest(self, *a, **kw):
        return self.ok("ingest", "--source", "claude", *a, root="", **kw)

    def logs(self):
        out = {}
        for dp, _, fns in os.walk(os.path.join(self.store, "log")):
            for f in fns:
                p = os.path.join(dp, f)
                st = os.stat(p)
                out[p] = (st.st_size, st.st_mtime_ns)
        return out

    def rows(self, sid=SID):
        res = []
        for p in sorted(self.logs()):
            if os.path.basename(p) == sid + ".jsonl":
                res += [json.loads(x) for x in slurp(p).splitlines() if x.strip()]
        return res

    def outpath(self, sid=SID):
        return next(p for p in self.logs() if os.path.basename(p) == sid + ".jsonl")


class TestIngest(Ing):
    def test_roundtrip(self):
        rows = self.base_rows()
        self.put(rows)
        self.assertIn("5 rows", self.ingest().stdout)
        got = self.rows()
        self.assertEqual([g["raw"] for g in got], rows)
        self.assertEqual([g["seq"] for g in got], list(range(5)))
        g = got[1]
        self.assertEqual((g["v"], g["src"], g["adapter"], g["session"], g["secret_flags"]), (1, "claude", 1, SID, 0))
        self.assertTrue(g["ingested"].endswith("Z"))
        self.assertEqual(g["src_ref"], "-work-parsekit/%s.jsonl:1" % SID)
        self.assertEqual(os.path.basename(os.path.dirname(self.outpath())), "2026-10")
        self.assertEqual(os.path.basename(os.path.dirname(os.path.dirname(self.outpath()))), "claude")

    def test_perms(self):
        self.put(self.base_rows())
        self.ingest()
        for dp, dns, fns in os.walk(self.store):
            self.assertEqual(stat.S_IMODE(os.stat(dp).st_mode), 0o700, dp)
            for f in fns:
                self.assertEqual(stat.S_IMODE(os.stat(os.path.join(dp, f)).st_mode), 0o600, f)

    def test_perms_under_open_umask(self):
        self.put(self.base_rows())
        subprocess.run("umask 000; exec %s -I %s ingest --source claude" % (sys.executable, AWT), shell=True, env=self.env, check=True, capture_output=True)
        for dp, dns, fns in os.walk(self.store):
            self.assertEqual(stat.S_IMODE(os.stat(dp).st_mode), 0o700, dp)
            for f in fns:
                self.assertEqual(stat.S_IMODE(os.stat(os.path.join(dp, f)).st_mode), 0o600, f)

    def test_rerun_writes_nothing(self):
        self.put(self.base_rows())
        self.ingest()
        before = self.logs()
        r = self.ingest()
        self.assertIn("0 rows", r.stdout)
        self.assertEqual(self.logs(), before)

    def test_incremental_append(self):
        self.put(self.base_rows())
        self.ingest()
        self.put([rec("user", 4, "next"), rec("assistant", 5, "ok")], mode="ab")
        self.assertIn("2 rows", self.ingest().stdout)
        self.assertEqual([g["seq"] for g in self.rows()], list(range(7)))
        self.assertEqual(self.rows()[6]["raw"]["uuid"], "u-5")

    def test_secrets_flagged_not_altered(self):
        rows = [rec("user", 0, "token %s and %s" % (GH, AKIA)), rec("assistant", 1, "clean"),
                rec("user", 2, [{"type": "tool_result", "tool_use_id": "t", "content": "key=" + AKIA}])]
        self.put(rows)
        self.ingest()
        got = self.rows()
        self.assertEqual([g["secret_flags"] for g in got], [2, 0, 1])
        self.assertEqual([g["raw"] for g in got], rows)
        self.assertIn(GH, slurp(self.outpath()))

    def test_no_size_cap(self):
        big = "x" * 600000
        self.put([rec("user", 0, [{"type": "tool_result", "tool_use_id": "t", "content": big}])])
        self.ingest()
        self.assertEqual(self.rows()[0]["raw"]["message"]["content"][0]["content"], big)

    def test_source_untouched(self):
        p = self.put(self.base_rows())
        before = (hashlib.sha256(slurp(p, "rb")).hexdigest(), os.stat(p).st_mtime_ns, os.stat(p).st_ino)
        self.ingest()
        self.ingest()
        self.assertEqual(before, (hashlib.sha256(slurp(p, "rb")).hexdigest(), os.stat(p).st_mtime_ns, os.stat(p).st_ino))
        self.assertEqual(os.listdir(self.pdir), [SID + ".jsonl"])

    def test_unparsable_line_kept(self):
        self.put([line(rec("user", 0, "a")), b"this is not json\n", line(rec("user", 1, "b"))])
        self.ingest()
        got = self.rows()
        self.assertEqual(len(got), 3)
        self.assertEqual(got[1]["raw"], {"_unparsed": "this is not json"})

    def test_torn_source_tail_waits(self):
        full = line(rec("assistant", 1, "second"))
        self.put([line(rec("user", 0, "first")), full[:20]])
        self.assertIn("1 rows", self.ingest().stdout)
        self.put([full[20:]], mode="ab")
        self.assertIn("1 rows", self.ingest().stdout)
        self.assertEqual([g["raw"]["uuid"] for g in self.rows()], ["u-0", "u-1"])

    def test_torn_output_tail_healed(self):
        self.put(self.base_rows())
        self.ingest()
        op = self.outpath()
        with open(op, "ab") as g:
            g.write(b'{"v":1,"src":"claude","seq":99,"ra')  # a crashed writer
        self.put([rec("user", 4, "more")], mode="ab")
        self.ingest()
        good = []
        for x in slurp(op).splitlines():
            try:
                good.append(json.loads(x))
            except ValueError:
                pass
        self.assertEqual([g["seq"] for g in good], list(range(6)))
        self.assertTrue(slurp(op).endswith("\n"))

    def test_crash_before_offsets_saved_no_duplicates(self):
        self.put(self.base_rows())
        self.ingest()
        for dp, _, fns in os.walk(self.store):
            for f in fns:
                if "offsets" in f:
                    os.unlink(os.path.join(dp, f))  # as if the run died after appending, before saving offsets
        self.put([rec("user", 4, "more")], mode="ab")
        self.ingest()
        self.assertEqual([g["seq"] for g in self.rows()], list(range(6)))
        self.assertEqual([g["raw"].get("uuid") for g in self.rows()][-1], "u-4")

    def test_truncated_source_rescans_without_duplicates(self):
        rows = self.base_rows()
        p = self.put(rows)
        self.ingest()
        self.put(rows[:2], path=p)  # shorter than the saved offset, same inode
        self.assertIn("0 rows", self.ingest().stdout)
        self.put(rows[:2] + [rec("user", 9, "after the cut")], path=p)
        self.ingest()
        self.assertEqual([g["raw"].get("uuid") for g in self.rows()][-1], "u-9")
        self.assertEqual(len(self.rows()), 6)
        self.assertEqual([g["seq"] for g in self.rows()], list(range(6)))

    def test_rotated_source_same_content_writes_nothing(self):
        rows = self.base_rows()
        p = self.put(rows)
        self.ingest()
        before = self.logs()
        os.rename(p, p + ".old")
        self.put(rows, path=p)  # new inode, same rows
        self.ingest()
        self.assertEqual(self.logs(), before)

    def test_rotated_source_new_content_appends(self):
        p = self.put(self.base_rows())
        self.ingest()
        os.unlink(p)
        self.put([rec("user", 7, "fresh start")], path=p)
        self.ingest()
        self.assertEqual(len(self.rows()), 6)
        self.assertEqual([g["seq"] for g in self.rows()], list(range(6)))

    def test_subagent_and_second_session(self):
        self.put(self.base_rows())
        other = "9a9a9a9a-0000-4000-8000-00000000bbbb"
        self.put([rec("user", 0, "other")], path=self.src(other))
        sub = self.put([rec("user", 0, "sub", isSidechain=True, agentId="ab12")], path=self.src(sub="agent-ab12"))
        self.ingest()
        names = sorted(os.path.basename(p) for p in self.logs())
        self.assertEqual(len(names), 3)
        self.assertIn(other + ".jsonl", names)
        self.assertEqual(len(self.rows()), 5)

    def test_concurrent_ingests(self):
        self.put(self.base_rows())
        procs = [subprocess.Popen([sys.executable, "-I", AWT, "ingest", "--source", "claude"], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(8)]
        for p in procs:
            p.communicate()
            self.assertEqual(p.returncode, 0)
        self.assertEqual([g["seq"] for g in self.rows()], list(range(5)))

    def test_concurrent_with_growing_source(self):
        p = self.put(self.base_rows())
        procs = []
        for i in range(6):
            self.put([rec("user", 10 + i, "m%d" % i)], path=p, mode="ab")
            procs.append(subprocess.Popen([sys.executable, "-I", AWT, "ingest", "--source", "claude"], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        for q in procs:
            q.communicate()
        self.ingest()
        self.assertEqual([g["seq"] for g in self.rows()], list(range(11)))

    def test_missing_source_dir_is_not_an_error(self):
        self.env["AWT_CLAUDE_PROJECTS"] = os.path.join(self.tmp, "nope")
        self.assertIn("0 rows", self.ingest().stdout)

    def test_source_all_and_unknown_source(self):
        self.put(self.base_rows())
        self.ok("ingest", "--source", "all", root="")
        self.assertEqual(len(self.rows()), 5)
        self.bad("ingest", "--source", "pi", root="", code=2)

    def test_hook_is_silent_and_exits_zero(self):
        self.put(self.base_rows())
        r = self.ok("ingest", "--source", "claude", "--hook", root="")
        self.assertEqual((r.stdout, r.stderr), ("", ""))
        self.assertEqual(len(self.rows()), 5)
        blocker = os.path.join(self.tmp, "afile")
        open(blocker, "w").close()
        self.env["AWT_STORE"] = os.path.join(blocker, "store")  # cannot be created
        r = self.ok("ingest", "--source", "claude", "--hook", root="")
        self.assertEqual((r.stdout, r.stderr), ("", ""))
        r = self.bad("ingest", "--source", "claude", root="")
        self.assertIn("fix:", r.stderr)

    def test_store_default_location(self):
        env = dict(self.env)
        for k in ("AWT_STORE", "XDG_DATA_HOME"):
            env.pop(k, None)
        self.put(self.base_rows())
        self.ok("ingest", "--source", "claude", root="", env=env)
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, ".local", "share", "awt-store", "log", "claude")))
        env["XDG_DATA_HOME"] = os.path.join(self.tmp, "xdg")
        self.ok("ingest", "--source", "claude", root="", env=env)
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "xdg", "awt-store", "log", "claude")))

    def test_save_removed_and_verb_count(self):
        r = self.bad("save", "m", code=2)
        self.assertIn("git commit", r.stderr)
        self.assertIn("awt doctor --staged", r.stderr)
        self.assertIn("fix:", r.stderr)
        loader = importlib.machinery.SourceFileLoader("awt_mod", AWT)
        spec = importlib.util.spec_from_loader("awt_mod", loader)
        m = importlib.util.module_from_spec(spec)
        loader.exec_module(m)
        verbs = m.build()._subparsers._group_actions[0].choices
        self.assertIn("ingest", verbs)
        self.assertNotIn("save", verbs)
        self.assertLessEqual(len([v for v in verbs if v != "help"]), 16)

    def test_init_settings_has_session_end_hook(self):
        self.init()
        s = json.loads(slurp(self.p(".claude", "settings.json")))
        cmds = [h["command"] for g in s["hooks"]["SessionEnd"] for h in g["hooks"]]
        self.assertTrue(any(c.endswith("awt ingest --source claude --hook") for c in cmds))
        self.assertTrue(any("resume --hook" in h["command"] for g in s["hooks"]["SessionStart"] for h in g["hooks"]))


class TestDoctorStore(Ing):
    def doctor(self, **kw):
        self.init()
        return self.awt("doctor", **kw).stdout

    def test_never_run_warns_then_fresh_ok(self):
        out = self.doctor()
        self.assertRegex(out, r"warn .*ingest.*never")
        self.put(self.base_rows())
        self.ingest()
        out = self.awt("doctor").stdout
        self.assertRegex(out, r"ok .*ingest")
        self.assertNotRegex(out, r"warn .*ingest")

    def test_stale_ingest_warns(self):
        self.put(self.base_rows())
        self.ingest()
        for dp, _, fns in os.walk(self.store):
            for f in fns:
                if "offsets" in f:
                    p = os.path.join(dp, f)
                    d = json.loads(slurp(p))
                    d["last_run"] = "2020-01-01T00:00:00.000Z"
                    with open(p, "w") as g:
                        json.dump(d, g)
        self.assertRegex(self.awt("doctor").stdout, r"warn .*ingest.*days")

    def test_store_mode_and_location(self):
        self.put(self.base_rows())
        self.ingest()
        self.assertRegex(self.awt("doctor").stdout, r"ok .*store mode")
        os.chmod(self.store, 0o755)
        self.assertRegex(self.awt("doctor").stdout, r"warn .*store.*755")
        os.chmod(self.store, 0o700)
        os.chmod(self.outpath(), 0o644)
        self.assertRegex(self.awt("doctor").stdout, r"warn .*files.*chmod")
        os.chmod(self.outpath(), 0o600)
        sub = os.path.join(self.tmp, "repo")
        os.makedirs(sub)
        subprocess.run(["git", "init", "-q", sub], check=True, env=self.env)
        self.env["AWT_STORE"] = os.path.join(sub, "s")
        self.assertRegex(self.awt("doctor").stdout, r"warn .*git")
        self.env["AWT_STORE"] = os.path.join(self.tmp, "Dropbox", "s")
        self.assertRegex(self.awt("doctor").stdout, r"warn .*sync")

    def test_retention_vs_cleanup_period(self):
        p = self.put(self.base_rows())
        old = time.time() - 40 * 86400
        os.utime(p, (old, old))
        out = self.doctor()
        self.assertRegex(out, r"warn .*oldest Claude transcript is 40 days.*30")
        with open(self.env["AWT_CLAUDE_SETTINGS"], "w") as g:
            json.dump({"cleanupPeriodDays": 3650}, g)
        out = self.awt("doctor").stdout
        self.assertRegex(out, r"ok .*oldest Claude transcript is 40 days.*3650")

    def test_doctor_does_not_create_store(self):
        self.doctor()
        self.assertFalse(os.path.exists(self.store))


class TestDoctorStaged(Base):
    def git(self, *a):
        return subprocess.run(["git", "-C", self.root] + list(a), capture_output=True, text=True, env=self.env)

    def test_staged(self):
        os.makedirs(self.root, exist_ok=True)
        self.assertEqual(self.git("init", "-q").returncode, 0)
        self.write("ok.txt", "fine\n")
        self.git("add", "ok.txt")
        r = self.ok("doctor", "--staged")
        self.assertIn("ok", r.stdout)
        self.write("leak.txt", "k=" + AKIA + "\n")
        self.git("add", "leak.txt")
        r = self.bad("doctor", "--staged")
        self.assertIn("leak.txt", r.stderr)
        self.assertIn("aws-access-key", r.stderr)
        self.assertNotIn(AKIA, r.stderr + r.stdout)
        # the staged blob is what counts, not the working copy
        self.write("leak.txt", "clean now\n")
        self.bad("doctor", "--staged")
        self.git("add", "leak.txt")
        self.ok("doctor", "--staged")
        # runs from a pre-commit hook: cwd is the repo, no --dir
        self.write("leak.txt", "k=" + AKIA + "\n")
        self.git("add", "leak.txt")
        self.bad("doctor", "--staged", root="", cwd=self.root)

    def test_not_a_repo(self):
        r = self.bad("doctor", "--staged", root=self.tmp)
        self.assertIn("fix:", r.stderr)


if __name__ == "__main__":
    unittest.main()
