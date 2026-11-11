"""Spec rows the first audit found untested: doctor levels, I8, effect claim expiry, migrate-paseo exit codes, small invariants."""
import datetime, json, os, re, shutil, socket, stat, subprocess, sys, unittest

import test_awt
from test_awt import AWT, AKIA, Base, slurp

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRE_TREE = "388cf89"  # the release before the node tree


def levels(out):
    return {l.split(" ", 1)[0] for l in out.splitlines()}


def line_with(out, text):
    hit = [l for l in out.splitlines() if text in l]
    assert hit, (text, out)
    return hit[0].split(" ", 1)[0]


class Doctor(Base):
    def test_clean_standalone_is_all_ok(self):
        self.init()
        os.chmod(self.p(".."), 0o755)
        r = self.ok("doctor")
        self.assertNotIn("fail", levels(r.stdout), r.stdout)
        self.assertEqual(line_with(r.stdout, "O_APPEND"), "ok")

    def test_fail_when_agents_block_is_missing(self):
        self.init()
        os.unlink(self.p("AGENTS.md"))
        r = self.bad("doctor")
        self.assertEqual(line_with(r.stdout, "AGENTS.md"), "fail")

    @unittest.skipIf(os.geteuid() == 0, "root reads anything")
    def test_fail_when_events_are_unreadable(self):
        self.init()
        os.chmod(self.p(".awt", "events.jsonl"), 0)
        self.addCleanup(os.chmod, self.p(".awt", "events.jsonl"), 0o644)
        r = self.bad("doctor")
        self.assertEqual(line_with(r.stdout, "events.jsonl"), "fail")

    @unittest.skipIf(os.geteuid() == 0, "root writes anywhere")
    def test_fail_when_the_append_probe_cannot_run(self):
        self.init()
        os.chmod(self.p(".awt"), 0o500)
        self.addCleanup(os.chmod, self.p(".awt"), 0o755)
        r = self.bad("doctor")
        self.assertEqual(line_with(r.stdout, "O_APPEND"), "fail")

    def test_warns_do_not_fail(self):
        self.init()
        self.write("../CLAUDE.md", "x\n")
        os.unlink(self.p(".claude", "settings.json"))
        subprocess.run(["git", "init", "-q", self.root], check=True, env=self.env)
        subprocess.run(["git", "-C", self.root, "remote", "add", "origin", "https://example.invalid/x.git"], check=True, env=self.env)
        e = self.ok("effect", "plan", "--target", "slack:#eng", "--run", "exit 3").stdout.split()[0]
        self.bad("effect", "apply", e, "--target", "slack:#eng")
        r = self.ok("doctor")  # exit 0: warnings only
        for text in ("CLAUDE.md", "settings", "awt is not executable", "git remote", "unknown/conflict effects"):
            self.assertEqual(line_with(r.stdout, text), "warn", (text, r.stdout))
        self.assertNotIn("fail", levels(r.stdout))

    def test_warn_on_a_sync_folder(self):
        root = os.path.join(self.tmp, "iCloud", "task")
        os.makedirs(root)
        self.ok("init", "--goal", "g", "--done", "d", root=root)
        self.assertEqual(line_with(self.ok("doctor", root=root).stdout, "sync folder"), "warn")

    def test_executable_awt_and_settings_are_ok(self):
        self.init()
        shutil.copy2(AWT, self.p("awt"))
        r = self.ok("doctor")
        self.assertEqual(line_with(r.stdout, "awt is executable"), "ok")
        self.assertEqual(line_with(r.stdout, "settings has"), "ok")


class PreTreeBrief(Base):
    def test_standalone_brief_is_byte_identical_to_the_pre_tree_release(self):  # I8
        g = subprocess.run(["git", "-C", REPO, "show", "%s:awt" % PRE_TREE], capture_output=True)
        if g.returncode:
            self.skipTest("history for %s is not available" % PRE_TREE)
        old = os.path.join(self.tmp, "old-awt")
        with open(old, "wb") as f:
            f.write(g.stdout)

        def run(script, *a):
            r = subprocess.run([sys.executable, "-I", script, "--dir", self.root] + list(a), capture_output=True, text=True, env=self.env, cwd=self.tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout
        run(old, "init", "--goal", "ship parsekit", "--done", "merged")
        run(old, "decide", "use the ast", "--why", "faster", "--tag", "rule")
        run(old, "decide", "keep tokens", "--why", "simple")
        run(old, "ask", "who owns the lexer?")
        run(old, "state", "--now", "lexer done", "--next", "parser")
        run(old, "note", "parsekit fixtures live in fixtures/")
        run(old, "ref", "https://example.invalid/pr/1", "--title", "the pr")
        self.write("docs/plan.md", "# plan\n")
        self.write("outbox/m.md", "hi\n")
        run(old, "effect", "plan", "--target", "slack:#eng", "--body", "outbox/m.md")
        # ages are shown in coarse units: push every row ten days back so a clock tick cannot change them
        past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        p = self.p(".awt", "events.jsonl")
        with open(p) as f:
            txt = re.sub(r'"ts": ?"[^"]*"', '"ts":"%s"' % past, f.read())
        with open(p, "w") as f:
            f.write(txt)
        for args in (("resume",), ("resume", "--hook"), ("resume", "--scope", "main")):
            self.assertEqual(run(AWT, *args), run(old, *args), args)


class ClaimExpiry(Base):
    def claim(self, e, age, timeout):
        row = dict(v=1, ts=(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=age)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                   host=socket.gethostname(), by="t", type="effect", id=e, step="claimed", attempt=1, pid=os.getpid(), timeout=timeout)
        with open(self.p(".awt", "events.jsonl"), "ab") as g:
            g.write((json.dumps(row) + "\n").encode())

    def state(self, e):
        return [l.split(":", 1)[1].strip() for l in self.ok("effect", "show", e).stdout.splitlines() if l.startswith("state:")][0]

    def test_claim_lapses_after_timeout_plus_30s(self):  # live pid, so only the clock can expire it
        self.init()
        inside = self.ok("effect", "plan", "--target", "a", "--run", "true").stdout.split()[0]
        self.claim(inside, age=100 + 20, timeout=100)
        self.assertEqual(self.state(inside), "claimed")
        outside = self.ok("effect", "plan", "--target", "b", "--run", "true").stdout.split()[0]
        self.claim(outside, age=100 + 40, timeout=100)
        self.assertEqual(self.state(outside), "unknown")


class SmallInvariants(Base):
    def test_no_flag_bypasses_the_secret_scan(self):
        self.init()
        for flag in ("--force", "--allow-secret", "--no-scan", "--yes"):
            r = self.bad("note", "key " + AKIA, flag, code=2)
        r = self.bad("note", "key " + AKIA)
        self.assertNotIn(AKIA, r.stdout + r.stderr)
        self.assertEqual(self.rows("note"), [])

    def test_default_by_is_agent(self):
        self.init()
        self.ok("note", "x")
        self.assertEqual(self.rows("note")[0]["by"], "agent")

    def test_capture_input_may_be_anywhere_but_body_may_not(self):
        self.init()
        outside = os.path.join(self.tmp, "elsewhere.txt")
        with open(outside, "w") as f:
            f.write("pasted\n")
        self.ok("capture", "--from", "slack", "--title", "t", outside)
        self.bad("effect", "plan", "--target", "x", "--body", outside)

    def test_find_skips_binary_big_script_and_scratch(self):
        self.init()
        shutil.copy2(AWT, self.p("awt"))
        self.write("docs/seen.md", "needle here\n")
        self.write("scratch/s.md", "needle here\n")
        with open(self.p("docs", "bin.dat"), "wb") as f:
            f.write(b"\0\0needle\0")
        with open(self.p("docs", "big.txt"), "w") as f:
            f.write("needle\n" + "x" * (2 * 1024 * 1024 + 10))
        out = self.ok("find", "needle").stdout
        self.assertIn("docs/seen.md", out)
        for hidden in ("scratch/", "bin.dat", "big.txt", "awt:"):
            self.assertNotIn(hidden, out)

    def test_save_never_pushes_and_never_signs(self):
        self.init()
        remote = os.path.join(self.tmp, "remote.git")
        subprocess.run(["git", "init", "-q", "--bare", remote], check=True, env=self.env)
        subprocess.run(["git", "init", "-q", self.root], check=True, env=self.env)
        subprocess.run(["git", "-C", self.root, "remote", "add", "origin", remote], check=True, env=self.env)
        subprocess.run(["git", "-C", self.root, "config", "commit.gpgsign", "true"], check=True, env=self.env)
        subprocess.run(["git", "-C", self.root, "config", "gpg.program", "/nonexistent-gpg"], check=True, env=self.env)
        self.ok("save", "snapshot")
        self.assertEqual(subprocess.run(["git", "-C", remote, "rev-list", "--all", "--count"], capture_output=True, text=True, env=self.env).stdout.strip(), "0")
        self.assertIn("snapshot", subprocess.run(["git", "-C", self.root, "log", "--format=%s"], capture_output=True, text=True, env=self.env).stdout)

    def test_ref_kinds_jira_and_merge_requests(self):
        self.init()
        for target, kind in (("https://acme.atlassian.net/browse/PK-12", "jira"), ("https://git.example.invalid/g/p/-/merge_requests/7", "pr")):
            self.ok("ref", target, "--title", "t")
        kinds = {r["target"]: r["kind"] for r in self.rows("ref")}
        self.assertEqual(kinds["https://acme.atlassian.net/browse/PK-12"], "jira")
        self.assertEqual(kinds["https://git.example.invalid/g/p/-/merge_requests/7"], "pr")

    def test_supersede_suffixes_on_collision(self):
        self.init()
        for n in ("old.md", "new.md"):
            self.write("docs/" + n, n + "\n")
        self.write("docs/_superseded/old.md", "taken\n")
        self.ok("supersede", "docs/old.md", "docs/new.md")
        self.assertEqual(slurp(self.p("docs", "_superseded", "old.md")), "taken\n")
        self.assertEqual(slurp(self.p("docs", "_superseded", "old-2.md")), "old.md\n")

    def test_effect_apply_timeout_zero_is_usage_error(self):
        self.init()
        e = self.ok("effect", "plan", "--target", "t", "--run", "true").stdout.split()[0]
        self.bad("effect", "apply", e, "--target", "t", "--timeout", "0", code=2)

    def test_init_warns_about_claude_md(self):
        parent = os.path.join(self.tmp, "p")
        os.makedirs(os.path.join(parent, "task"))
        with open(os.path.join(parent, "CLAUDE.md"), "w") as f:
            f.write("x\n")
        r = self.ok("init", "--goal", "g", "--done", "d", root=os.path.join(parent, "task"))
        self.assertIn("@AGENTS.md", r.stderr)

    def test_awt_is_one_stdlib_file(self):
        src = slurp(AWT)
        self.assertTrue(src.startswith("#!"))
        imports = set(re.findall(r"^\s*(?:import|from)\s+([A-Za-z_][\w]*)", src, re.M))
        for m in imports:
            self.assertIn(m, sys.stdlib_module_names, m)

    def test_no_command_prompts(self):
        self.init()
        r = subprocess.run([sys.executable, "-I", AWT, "--dir", self.root, "note", "x"], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual(r.returncode, 0)


class Relay(unittest.TestCase):
    def test_relay_never_applies_effects_or_bypasses_permissions(self):
        src = slurp(os.path.join(REPO, "relay"))
        self.assertEqual(src.count("effect apply"), 1, "only the help text may name it")
        self.assertNotIn('"effect"', src)
        for flag in ("dangerously-skip-permissions", "bypassPermissions", "acceptEdits"):
            self.assertNotIn(flag, src)


if __name__ == "__main__":
    unittest.main()
