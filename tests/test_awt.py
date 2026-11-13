import ast, datetime, json, os, shutil, socket, subprocess, sys, tempfile, time, unittest

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
            self.plan("--how", "true", target="slack:#" + long(150, "c%d" % i).replace(" ", "-"))
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

    def test_save_was_removed(self):
        self.init()
        r = self.bad("save", "m", code=2)
        self.assertIn("git commit", r.stderr)
        self.assertIn("awt doctor --staged", r.stderr)


class TestEffects(Base):
    """Declared effects (SPEC section 10): awt keeps the ledger and never runs anything."""

    def setUp(self):
        super().setUp()
        self.init()
        self.hits = self.p("hits.txt")

    def nhits(self):
        return len(slurp(self.hits).split()) if os.path.exists(self.hits) else 0

    def mark(self, eid, to, *extra, code=0):
        return self.bad("effect", "mark", eid, to, *extra, code=code) if code else self.ok("effect", "mark", eid, to, *extra)

    def begin(self, eid, code=0):
        return self.bad("effect", "begin", eid, code=code) if code else self.ok("effect", "begin", eid)

    def key_of(self, e):
        return [r for r in self.rows("effect") if r["id"] == e][0]["key"]

    def test_declared_flow(self):
        self.write("outbox/m.md", "hello\n")
        r = self.ok("effect", "plan", "--target", "slack:#eng", "--body", "outbox/m.md", "--how", "echo hi >> hits.txt")
        e = r.stdout.split()[0]
        self.assertIn("effect begin %s" % e, r.stdout)
        self.assertEqual(self.state_of(e), "planned")
        self.assertIn("already planned", self.ok("effect", "plan", "--target", "slack:#eng", "--body", "outbox/m.md", "--how", "other").stdout)
        self.assertIn("[planned]", self.ok("list", "outbox").stdout)
        r = self.begin(e)
        for want in ("outbox/m.md", "how: echo hi >> hits.txt", "effect mark %s sent" % e):
            self.assertIn(want, r.stdout)
        self.assertTrue(os.path.exists(self.p(".awt", "claims", self.key_of(e) + ".1")))
        self.assertEqual(self.state_of(e), "begun")
        self.mark(e, "sent", "--ref", "https://example.invalid/m/1")
        self.assertEqual(self.state_of(e), "sent")
        show = self.ok("effect", "show", e).stdout
        self.assertIn("https://example.invalid/m/1", show)
        self.assertIn("how: echo hi >> hits.txt", show)
        self.assertEqual(self.nhits(), 0)  # --how is text, never run
        for to in ("sent", "not-sent", "unknown", "dropped"):
            self.mark(e, to, "--why", "w", code=1)
        self.begin(e, code=1)
        self.assertEqual([r["step"] for r in self.rows("effect")], ["planned", "begun", "sent"])

    def test_person_marks_sent_straight_from_planned(self):
        e = self.plan()
        self.mark(e, "sent")
        self.assertEqual(self.state_of(e), "sent")

    def test_marks_legal_from_planned_only_sent_and_dropped(self):
        e = self.plan()
        for to in ("not-sent", "unknown"):
            self.mark(e, to, "--why", "w", code=1)
        self.mark(e, "dropped")
        self.assertEqual(self.state_of(e), "dropped")
        for to in ("sent", "not-sent", "unknown", "dropped"):
            self.mark(e, to, "--why", "w", code=1)
        r = self.bad("effect", "plan", "--target", "slack:#eng")
        self.assertIn("--again", r.stderr)
        self.assertNotEqual(self.plan("--again"), e)

    def test_begin_claims_once(self):
        e = self.plan()
        self.begin(e)
        r = self.begin(e, code=1)
        self.assertIn("fix:", r.stderr)
        e2 = self.plan("--again", target="t2")
        open(self.p(".awt", "claims", self.key_of(e2) + ".1"), "w").close()  # a claim with no row reads as begun
        self.assertIn("begun", self.begin(e2, code=1).stderr)
        self.bad("effect", "begin", "e-00000000", code=4)

    def test_concurrent_begin_wins_once(self):
        e = self.plan()
        cmd = [sys.executable, "-I", AWT, "--dir", self.root, "effect", "begin", e]
        ps = [subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env) for _ in range(6)]
        codes = []
        for p in ps:
            p.communicate()
            codes.append(p.returncode)
        self.assertEqual(sorted(codes), [0] + [1] * 5)
        self.assertEqual(len([r for r in self.rows("effect") if r["step"] == "begun"]), 1)

    def test_not_sent_returns_to_planned_with_next_attempt(self):
        e = self.plan()
        self.begin(e)
        self.mark(e, "not-sent", code=2)  # needs --why
        self.mark(e, "not-sent", "--why", "gateway refused")
        self.assertEqual(self.state_of(e), "planned")
        self.assertEqual([r["attempt"] for r in self.rows("effect")][-1], 2)
        self.begin(e)
        self.assertTrue(os.path.exists(self.p(".awt", "claims", self.key_of(e) + ".2")))
        self.mark(e, "sent")

    def test_unknown_needs_why_and_resolves_only_to_sent_or_not_sent(self):
        e = self.plan()
        self.begin(e)
        self.mark(e, "unknown", code=2)
        self.mark(e, "unknown", "--why", "timed out")
        self.assertEqual(self.state_of(e), "unknown")
        self.assertIn(e, self.ok("resume").stdout)
        self.mark(e, "dropped", code=1)
        self.mark(e, "unknown", "--why", "again", code=1)
        self.write("outbox/o.md", "other\n")
        r = self.bad("effect", "plan", "--target", "slack:#eng", "--body", "outbox/o.md")  # open unknown on the target
        self.assertIn("unknown", r.stderr)
        self.mark(e, "not-sent", "--why", "checked, nothing there")
        self.assertEqual(self.state_of(e), "planned")
        self.begin(e)
        self.mark(e, "unknown", "--why", "x")
        self.mark(e, "sent")
        self.assertEqual(self.state_of(e), "sent")

    def test_after_ordering(self):
        self.bad("effect", "plan", "--target", "t", "--after", "e-00000000", code=4)
        a = self.plan(target="A")
        b = self.plan("--after", a, target="B")
        self.begin(b, code=1)
        self.begin(a)
        self.mark(a, "sent")
        self.begin(b)

    def test_changed_body_refuses_begin(self):
        self.write("outbox/m.md", "v1\n")
        e = self.plan("--body", "outbox/m.md")
        self.write("outbox/m.md", "v2\n")
        self.assertIn("plan again", self.begin(e, code=1).stderr)
        self.assertEqual(self.state_of(e), "planned")

    def test_again_makes_new_key(self):
        e1 = self.plan()
        self.assertEqual(self.plan(), e1)
        e2 = self.plan("--again")
        self.assertNotEqual(e1, e2)
        self.assertEqual(len({r["key"] for r in self.rows("effect")}), 2)

    def test_removed_verbs_and_flags_exit_2_with_a_fix(self):
        e = self.plan()
        for args in (("effect", "apply", e, "--target", "slack:#eng"), ("effect", "plan", "--target", "t", "--run", "true"),
                     ("effect", "plan", "--target", "t", "--snapshot", "true"), ("effect", "plan", "--target", "t", "--verify", "true"),
                     ("effect", "plan", "--target", "t", "--class", "overwrite"), ("effect", "apply", e, "--timeout", "5"),
                     ("effect", "plan", "--target", "t", "--run=true")):
            r = self.bad(*args, code=2)
            self.assertIn("fix:", r.stderr, args)
            for verb in ("plan", "begin", "mark"):
                self.assertIn(verb, r.stderr, args)
        self.assertEqual(len(self.rows("effect")), 1)
        for d in ("blobs", "runs"):
            self.assertFalse(os.path.exists(self.p(".awt", d)), d)

    def test_init_writes_no_ask_rule_and_no_outbox_paragraph(self):
        st = slurp(self.p(".claude", "settings.json"))
        self.assertNotIn("effect apply", st)
        self.assertNotIn('"ask"', st)
        json.loads(st)
        ag = slurp(self.p("AGENTS.md"))
        for gone in ("effect plan", "effect apply", "goes through the outbox"):
            self.assertNotIn(gone, ag)

    def test_status_done_blocked_while_begun(self):
        e = self.plan()
        self.assertIn(e, self.bad("status", "done").stderr)
        self.begin(e)
        r = self.bad("status", "done")
        self.assertIn(e, r.stderr)
        self.assertIn("begun", r.stderr)
        self.mark(e, "sent")
        self.ok("status", "done")

    def test_resume_shows_begun_and_unknown(self):
        a, b = self.plan(target="A"), self.plan(target="B")
        self.begin(a)
        self.begin(b)
        self.mark(b, "unknown", "--why", "w")
        out = self.ok("resume").stdout
        self.assertIn("%s begun" % a, out)
        self.assertIn("%s unknown" % b, out)

    def test_crash_claim_file_without_begun_row_reads_begun(self):
        e = self.plan()
        open(self.p(".awt", "claims", self.key_of(e) + ".1"), "w").close()
        self.assertEqual(self.state_of(e), "begun")
        self.assertIn(e, self.ok("resume").stdout)
        self.begin(e, code=1)
        self.mark(e, "dropped", code=1)
        self.mark(e, "not-sent", "--why", "w")
        self.assertEqual(self.state_of(e), "planned")
        e2 = self.plan("--again", target="other")
        open(self.p(".awt", "claims", self.key_of(e2) + ".1"), "w").close()
        self.mark(e2, "sent")
        self.assertEqual(self.state_of(e2), "sent")

    def test_missing_claims_dir_does_not_stop_begin(self):
        e = self.plan()
        shutil.rmtree(self.p(".awt", "claims"))
        self.begin(e)
        self.assertEqual(self.state_of(e), "begun")

    def test_illegal_rows_are_quarantined(self):
        e = self.plan()
        self.raw_append(dict(type="effect", id=e, step="unknown", attempt=1))  # planned -> unknown
        self.raw_append(dict(type="effect", id=e, step="planned", attempt=2))  # planned -> planned
        self.raw_append(dict(type="effect", id="e-ffffffff", step="sent", attempt=1))  # unknown id
        self.assertEqual(self.state_of(e), "planned")
        self.assertIn("3 quarantined", self.ok("resume").stdout)
        self.raw_append(dict(type="effect", id=e, step="sent", attempt=1))  # a person's mark, legal
        self.raw_append(dict(type="effect", id=e, step="begun", attempt=1))  # sent -> begun
        self.assertEqual(self.state_of(e), "sent")

    def test_no_code_path_runs_a_subprocess_for_an_effect(self):
        """Static: nothing reachable from an eff_* verb may start a process. Dynamic: --how text is inert."""
        tree = ast.parse(slurp(AWT))
        funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        banned = {"subprocess", "system", "popen", "execv", "execvp", "execl", "spawnv", "fork", "posix_spawn"}
        seen, todo = set(), [n for n in funcs if n.startswith("eff_")]
        self.assertGreaterEqual(len(todo), 4)
        while todo:
            name = todo.pop()
            if name in seen or name not in funcs:
                continue
            seen.add(name)
            for n in ast.walk(funcs[name]):
                if isinstance(n, ast.Attribute) and n.attr in banned or isinstance(n, ast.Name) and n.id in banned:
                    self.fail("%s reaches %s" % (name, getattr(n, "attr", getattr(n, "id", ""))))
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                    todo.append(n.func.id)
        self.assertIn("load", seen)
        e = self.plan("--how", "touch hits.txt; echo $(id) >> hits.txt")
        self.begin(e)
        self.mark(e, "sent")
        self.assertFalse(os.path.exists(self.hits))


class TestLegacyEffects(Base):
    """Trees written before declared effects: claimed reads as begun, legacy fields are shown, nothing on disk changes."""

    def setUp(self):
        super().setUp()
        self.init()
        self.raw_append(dict(type="effect", id="e-0000000a", step="planned", attempt=1, target="jira:PK-1", key="k" * 64,
                             body="outbox/c.md", body_sha="0" * 64, run="jira-cli comment PK-1", **{"class": "overwrite"},
                             snapshot="jira-cli show PK-1", verify="jira-cli show PK-1", why="legacy"))
        self.raw_append(dict(type="effect", id="e-0000000a", step="claimed", attempt=1, pid=999999, timeout=300))
        self.raw_append(dict(type="effect", id="e-0000000b", step="planned", attempt=1, target="slack:#eng", key="j" * 64, run="echo hi"))
        self.raw_append(dict(type="effect", id="e-0000000c", step="planned", attempt=1, target="slack:#ops", key="i" * 64, run="echo ho"))
        self.raw_append(dict(type="effect", id="e-0000000c", step="claimed", attempt=1, pid=999999, timeout=300))
        self.raw_append(dict(type="effect", id="e-0000000c", step="unknown", attempt=1, reason="exit code 3"))
        for d, n in (("runs", "e-0000000a.1.log"), ("blobs", "a" * 64)):
            os.makedirs(self.p(".awt", d), exist_ok=True)
            self.write(".awt/%s/%s" % (d, n), "old output\n")
        self.before = self.events()

    def test_claimed_reads_as_begun_and_unknown_stays(self):
        self.assertEqual(self.state_of("e-0000000a"), "begun")
        self.assertEqual(self.state_of("e-0000000c"), "unknown")
        out = self.ok("resume").stdout
        self.assertIn("e-0000000a begun", out)
        self.assertIn("e-0000000c unknown", out)
        self.assertNotIn("quarantined", out)

    def test_show_prints_legacy_fields_run_as_how_and_files(self):
        s = self.ok("effect", "show", "e-0000000a").stdout
        for want in ("how: jira-cli comment PK-1", "legacy class: overwrite", "legacy snapshot: jira-cli show PK-1",
                     "legacy verify: jira-cli show PK-1", "legacy file: .awt/runs/e-0000000a.1.log", "legacy file: .awt/blobs/" + "a" * 64):
            self.assertIn(want, s)
        j = [r for r in json.loads(self.ok("list", "effects", "--json").stdout) if r["id"] == "e-0000000a"][0]
        self.assertEqual(j["how"], "jira-cli comment PK-1")

    def test_planned_run_effect_is_an_ordinary_planned_effect(self):
        self.assertEqual(self.state_of("e-0000000b"), "planned")
        self.ok("effect", "begin", "e-0000000b")
        self.ok("effect", "mark", "e-0000000b", "sent")
        self.assertEqual(self.state_of("e-0000000b"), "sent")
        self.assertFalse(os.path.exists(self.p("hits.txt")))

    def test_legacy_begun_resolves_with_marks(self):
        self.ok("effect", "mark", "e-0000000a", "not-sent", "--why", "checked")
        self.assertEqual(self.state_of("e-0000000a"), "planned")
        self.ok("effect", "mark", "e-0000000c", "sent")

    def test_reads_and_marks_never_rewrite_the_log_or_delete_runs_and_blobs(self):
        for args in (("resume",), ("list", "effects"), ("effect", "show", "e-0000000a"), ("doctor",), ("status", "done")):
            self.awt(*args)
        self.assertEqual(self.events(), self.before)
        self.ok("effect", "mark", "e-0000000a", "sent")
        self.assertTrue(self.events().startswith(self.before))
        self.assertTrue(os.path.exists(self.p(".awt", "runs", "e-0000000a.1.log")))
        self.assertTrue(os.path.exists(self.p(".awt", "blobs", "a" * 64)))


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
