"""Spec rows the first audit found untested: doctor levels, I8, migrate-paseo exit codes, small invariants."""
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
        e = self.ok("effect", "plan", "--target", "slack:#eng").stdout.split()[0]
        self.ok("effect", "begin", e)
        self.ok("effect", "mark", e, "unknown", "--why", "timed out")
        r = self.ok("doctor")  # exit 0: warnings only
        for text in ("CLAUDE.md", "settings", "awt is not executable", "git remote", "begun/unknown effects"):
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


class DoctorAskRule(Base):
    OLD = '''{
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command", "command": "\\"$CLAUDE_PROJECT_DIR\\"/awt resume --hook" } ] }
    ]
  },
  "permissions": {
    "ask": [ "Bash(./awt effect apply *)", "Bash(awt effect apply *)" ]
  }
}
'''

    def test_old_ask_rule_warns_with_the_exact_line_and_is_never_edited(self):
        self.init()
        self.write(".claude/settings.json", self.OLD)
        r = self.ok("doctor")  # warning only: exit 0
        warn = [l for l in r.stdout.splitlines() if "ask rule" in l]
        self.assertEqual(len(warn), 1, r.stdout)
        self.assertTrue(warn[0].startswith("warn"))
        self.assertIn('line 8: "ask": [ "Bash(./awt effect apply *)", "Bash(awt effect apply *)" ]', warn[0])
        self.assertEqual(slurp(self.p(".claude", "settings.json")), self.OLD)
        self.assertEqual(line_with(r.stdout, "settings has"), "ok")

    def test_fresh_init_has_no_ask_rule_to_warn_about(self):
        self.init()
        self.assertNotIn("ask rule", self.ok("doctor").stdout)


class PreTreeBrief(Base):
    def test_standalone_brief_is_byte_identical_to_the_pre_tree_release(self):  # I8
        g = subprocess.run(["git", "-C", REPO, "show", "%s:awt" % PRE_TREE], capture_output=True)
        if g.returncode:
            self.skipTest("history for %s is not available" % PRE_TREE)
        old = os.path.join(self.tmp, "old-awt")
        with open(old, "wb") as f:
            f.write(g.stdout)

        def run(script, *a):
            if script == old and os.path.exists(self.p("BRIEF.md")):
                os.unlink(self.p("BRIEF.md"))  # the old awt knows no BRIEF.md and would count it as a changed file
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
        self.write("outbox/m.md", "hi\n")  # no effect row: its next-step line changed in phase 0 (declared effects)
        # ages are shown in coarse units: push every row ten days back so a clock tick cannot change them
        past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        p = self.p(".awt", "events.jsonl")
        with open(p) as f:
            txt = re.sub(r'"ts": ?"[^"]*"', '"ts":"%s"' % past, f.read())
        with open(p, "w") as f:
            f.write(txt)
        for args in (("resume",), ("resume", "--hook"), ("resume", "--scope", "main")):
            self.assertEqual(run(AWT, *args), run(old, *args), args)


class SmallInvariants(Base):
    def test_no_flag_bypasses_the_secret_scan(self):
        self.init()
        for flag in ("--force", "--allow-secret", "--no-scan", "--yes"):
            r = self.bad("note", "key " + AKIA, flag, code=2)
        r = self.bad("note", "key " + AKIA)
        self.assertNotIn(AKIA, r.stdout + r.stderr)
        self.assertEqual(self.rows("note"), [])

    def test_auto_state_does_not_reset_the_changes_baseline(self):
        # resume section 5: the plugin's stand-in handoff (scope auto) must not hide work since the agent's own
        import time
        self.init()
        self.ok("state", "--now", "own handoff", "--next", "n")
        time.sleep(1.1)
        with open(self.p("docs", "after-handoff.md"), "w") as f:
            f.write("x")
        time.sleep(1.1)
        self.ok("state", "--scope", "auto", "--now", "[auto] reply", "--next", "not recorded")
        self.assertIn("docs/after-handoff.md", self.ok("resume").stdout)

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
    def test_relay_never_runs_effects_or_bypasses_permissions(self):
        src = slurp(os.path.join(REPO, "relay"))
        self.assertNotIn("effect apply", src)
        self.assertNotIn('"effect"', src)
        for flag in ("dangerously-skip-permissions", "bypassPermissions", "acceptEdits"):
            self.assertNotIn(flag, src)


if __name__ == "__main__":
    unittest.main()
