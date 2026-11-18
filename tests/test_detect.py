"""Detected effects (SPEC Effects, 'Detected'): `awt ingest --event --hook` reads one tool-call event on stdin and writes the ledger.
Fixtures are a fictional `parsekit` project; token-shaped strings are built at run time."""
import fcntl, hashlib, importlib.machinery, importlib.util, json, os, stat, subprocess, sys, time, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_awt import AWT, Base, slurp

GH = "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0" * 2


def load_awt():
    spec = importlib.util.spec_from_loader("awt_mod", importlib.machinery.SourceFileLoader("awt_mod", AWT))
    m = importlib.util.module_from_spec(spec)
    saved = list(sys.path)
    try:
        spec.loader.exec_module(m)  # awt drops sys.path[0] when it loads
    finally:
        sys.path[:] = saved
    return m


MOD = load_awt()


def matched(cmd, tool="Bash"):
    inp = {"command": cmd} if tool == "Bash" else {}
    return [r for r, _t, _k in MOD.classify(tool, inp, "/work/parsekit")]


class Classify(unittest.TestCase):
    def test_outbound_commands_get_a_rule(self):
        want = {
            "git push": "git push", "git push origin feat/x": "git push", "git -C ../lib push": "git push",
            "cd lib && git add -A && git push --force-with-lease": "git push", "FOO=1 sudo git push": "git push",
            "gh pr create --title t --body b": "gh pr create", "gh pr comment 12 --body-file b.md": "gh pr comment",
            "gh issue close 3": "gh issue close", "gh pr merge 4 --squash": "gh pr merge", "gh pr edit 4 --title t": "gh pr edit",
            "gh release create v1 -F n.md": "gh release create", "gh api repos/o/r/issues -f title=t": "gh api POST",
            "gh api -X DELETE repos/o/r/issues/1": "gh api DELETE", "gh api --method PATCH repos/o/r/pulls/1": "gh api PATCH",
            "curl -X POST https://api.example.com/v1/m": "curl POST", "curl -d @body.json https://api.example.com/v1/m": "curl POST",
            "curl --json '{}' https://api.example.com": "curl POST", "curl -XPUT https://api.example.com/x": "curl PUT",
            "curl -F f=@a.txt https://up.example.com": "curl POST", "wget --post-data=a=1 https://api.example.com": "wget POST",
            "ssh deploy@build.example.com make": "ssh", "scp a.tgz deploy@build.example.com:/srv": "scp",
            "rsync -a out/ build.example.com:/srv/": "rsync", "npm publish": "npm publish", "cargo publish": "cargo publish",
            "twine upload dist/*": "twine upload", "bash -c 'git push origin main'": "git push",
            "git push <<EOF\nx\nEOF": "git push",
        }
        for cmd, rule in want.items():
            with self.subTest(cmd=cmd):
                self.assertEqual(matched(cmd), [rule])

    def test_local_reads_and_dry_runs_get_none(self):
        for cmd in ["git status", "git push --dry-run", "git push -n origin", "git log -1", "gh pr view 3", "gh pr list", "gh issue view 2",
                    "gh api repos/o/r/issues", "gh api -X GET repos/o/r", "curl https://example.com", "curl -s -I https://example.com",
                    "curl -X POST http://localhost:8080/x", "curl -d a=1 http://127.0.0.1:9/x", "curl -G -d q=1 https://example.com",
                    "wget https://example.com/f.tgz", "ssh localhost ls", "scp a b", "scp ./a.txt ./b.txt", "npm publish --dry-run", "npm install",
                    "echo git push", "grep 'git push' notes.md", "ls", "cat <<EOF\ngit push\nEOF", "git commit -m 'gh pr create'"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(matched(cmd), [])

    def test_mcp_tools_by_name(self):
        for t in ["mcp__slack__post_message", "mcp__jira__create_issue", "mcp__gh__add_comment", "mcp__x__publish_page", "mcp__mail__sendEmail"]:
            self.assertEqual(len(MOD.classify(t, {"channel": "c"}, "/w")), 1, t)
        for t in ["mcp__slack__list_channels", "mcp__paseo__create_agent", "Read", "Edit", "mcp__jira__get_issue"]:
            self.assertEqual(MOD.classify(t, {}, "/w"), [], t)

    def test_garbage_input_is_no_match_not_a_crash(self):
        for cmd in ["", "git push 'unterminated", None, 5, "\x00git push"]:
            MOD.classify("Bash", {"command": cmd}, "/w")
        MOD.classify("Bash", None, "/w")
        MOD.classify("Bash", {"command": "git push"}, None)

    def test_key_ignores_spacing_and_leading_cd_but_not_cwd_or_body(self):
        k = lambda cmd, cwd="/w": MOD.classify("Bash", {"command": cmd}, cwd)[0][2]
        self.assertEqual(k("git  push   origin main"), k("cd x && git push origin main"))
        self.assertNotEqual(k("git push origin main"), k("git push origin main", "/other"))
        self.assertNotEqual(k("git push origin main"), k("git push origin dev"))


class DetectBase(Base):
    def setUp(self):
        super().setUp()
        self.init()
        self.cwd = self.tmp
        self.env["XDG_CONFIG_HOME"] = os.path.join(self.tmp, "cfg")

    def ev(self, phase, cmd, cid="toolu_1", name=None, inp=None, cwd=None, by=None, **kw):
        """A Claude Code hook payload (PreToolUse / PostToolUse / PostToolUseFailure)."""
        p = {"hook_event_name": phase, "session_id": "s", "cwd": cwd or self.cwd, "tool_name": name or "Bash", "tool_input": inp if inp is not None else {"command": cmd}, "tool_use_id": cid}
        p.update(kw)
        return self.hook(p, by)

    def hook(self, payload, by=None, root=None, stdin=None):
        args = (["--by", by] if by else []) + ["ingest", "--event", "--hook"]
        r = self.awt(*args, input=stdin if stdin is not None else json.dumps(payload), root=root)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        return r.stdout

    def effects(self):
        return self.rows("effect")

    def steps(self):
        return [r["step"] for r in self.effects()]

    def asked(self, out):
        if not out.strip():
            return None
        o = json.loads(out)["hookSpecificOutput"]
        self.assertEqual((o["hookEventName"], o["permissionDecision"]), ("PreToolUse", "ask"))
        return o["permissionDecisionReason"]



class Detect(DetectBase):
    def test_pre_and_post_write_the_ledger_without_any_agent_call(self):
        self.assertEqual(self.ev("PreToolUse", "git push origin feat/x"), "")
        self.assertEqual(self.steps(), ["planned", "begun"])
        p = self.effects()[0]
        self.assertEqual((p["origin"], p["rule"], p["tool_call_id"], p["seen"]), ("detected", "git push", "toolu_1", "before"))
        self.assertIn("git push origin feat/x", p["target"])
        self.assertEqual(self.ev("PostToolUse", "git push origin feat/x", tool_response={"stdout": "ok"}), "")
        self.assertEqual(self.steps(), ["planned", "begun", "sent"])
        self.assertEqual(self.state_of(p["id"]), "sent")

    def test_every_detected_row_carries_a_model(self):
        """MODEL-TRACKING: the payload's model, else AWT_MODEL, else unknown:unset; never empty."""
        self.ev("PreToolUse", "git push origin a", "m1", model="claude-sonnet-5-5")
        self.ev("PostToolUse", "git push origin a", "m1", model={"id": "claude-opus-5-5"})
        self.assertEqual([r["model"] for r in self.effects()], ["claude-sonnet-5-5", "claude-sonnet-5-5", "claude-opus-5-5"][:len(self.effects())])
        self.env.pop("AWT_MODEL", None)
        self.ev("PreToolUse", "git push origin b", "m2")
        self.assertEqual(self.effects()[-1]["model"], "unknown:unset")
        self.env["AWT_MODEL"] = "us.test.model-1"
        self.ev("PreToolUse", "git push origin c", "m3")
        self.ev("PostToolUse", "git push origin c", "m3")
        self.assertEqual({r["model"] for r in self.effects()[-3:]}, {"us.test.model-1"})
        self.ev("PreToolUse", "git push origin d", "m4", model="")
        self.assertEqual(self.effects()[-1]["model"], "us.test.model-1")
        r = self.awt("--model", "flag-model", "ingest", "--event", "--hook", input=json.dumps({"hook_event_name": "PreToolUse", "cwd": self.cwd, "tool_name": "Bash", "tool_input": {"command": "git push origin e"}, "tool_use_id": "m5"}))
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(self.effects()[-1]["model"], "flag-model")  # phase 2's --model beats AWT_MODEL; a payload model beats both
        self.assertTrue(all(r.get("model") for r in self.effects()))

    def test_a_call_that_matches_nothing_takes_no_lock_and_writes_nothing(self):
        self.ev("PreToolUse", "ls")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".awt", "events.jsonl")) and self.effects())

    def test_non_outbound_is_not_recorded(self):
        for cmd in ["git status", "ls", "gh pr view 3"]:
            self.assertEqual(self.ev("PreToolUse", cmd), "")
            self.ev("PostToolUse", cmd)
        self.assertEqual(self.effects(), [])

    def test_exact_resend_of_a_sent_effect_asks_and_writes_nothing(self):
        self.ev("PreToolUse", "gh pr comment 12 --body-file b.md", "t1")
        self.ev("PostToolUse", "gh pr comment 12 --body-file b.md", "t1")
        first = self.effects()[0]["id"]
        n = len(self.effects())
        why = self.asked(self.ev("PreToolUse", "gh   pr comment 12 --body-file b.md", "t2"))
        self.assertIn(first, why)
        self.assertIn("sent", why)
        self.assertEqual(len(self.effects()), n)

    def test_resend_that_goes_ahead_is_recorded_after_the_fact(self):
        self.ev("PreToolUse", "gh pr merge 4", "t1")
        self.ev("PostToolUse", "gh pr merge 4", "t1")
        self.assertIsNotNone(self.asked(self.ev("PreToolUse", "gh pr merge 4", "t2")))
        self.ev("PostToolUse", "gh pr merge 4", "t2")  # the person said yes
        ids = {r["id"] for r in self.effects()}
        self.assertEqual(len(ids), 2)
        late = [r for r in self.effects() if r.get("tool_call_id") == "t2" and r["step"] == "planned"][0]
        self.assertEqual(late["seen"], "after")
        self.assertEqual([self.state_of(i) for i in sorted(ids)], ["sent", "sent"])
        self.ev("PostToolUse", "gh pr merge 4", "t2")  # a replayed event
        self.assertEqual({r["id"] for r in self.effects()}, ids)
        self.assertEqual(len(self.effects()), 6)

    def test_failure_and_interrupt_are_unknown_and_unknown_also_asks(self):
        self.ev("PreToolUse", "gh pr merge 4", "t1")
        self.ev("PostToolUseFailure", "gh pr merge 4", "t1", error="exit 1")
        i = self.effects()[0]["id"]
        self.assertEqual(self.state_of(i), "unknown")
        self.assertIn(i, self.asked(self.ev("PreToolUse", "gh pr merge 4", "t2")))
        self.ev("PreToolUse", "npm publish", "t3")
        self.ev("PostToolUse", "npm publish", "t3", tool_response={"interrupted": True})
        j = [r for r in self.effects() if r.get("rule") == "npm publish"][0]["id"]
        self.assertEqual(self.state_of(j), "unknown")

    def test_a_begun_duplicate_is_only_recorded(self):
        self.assertEqual(self.ev("PreToolUse", "gh pr merge 4", "t1"), "")
        self.assertEqual(self.ev("PreToolUse", "gh pr merge 4", "t2"), "")  # first one has no result yet: not sent, not unknown
        self.assertEqual(len({r["id"] for r in self.effects()}), 2)
        self.ev("PostToolUse", "gh pr merge 4", "t1")
        self.ev("PostToolUse", "gh pr merge 4", "t2")
        self.assertEqual(sorted(self.state_of(i) for i in {r["id"] for r in self.effects()}), ["sent", "sent"])

    def test_post_without_pre_is_recorded_after_the_fact(self):
        self.ev("PostToolUse", "gh pr create --title t", "t9")
        self.assertEqual(self.steps(), ["planned", "begun", "sent"])
        self.assertEqual(self.effects()[0]["seen"], "after")

    def test_body_file_cwd_and_command_are_part_of_the_key(self):
        os.makedirs(os.path.join(self.tmp, "w"))
        with open(os.path.join(self.tmp, "w", "b.md"), "w") as g:
            g.write("one")
        c = "gh pr comment 12 --body-file b.md"
        self.ev("PreToolUse", c, "t1", cwd=os.path.join(self.tmp, "w"))
        self.ev("PostToolUse", c, "t1", cwd=os.path.join(self.tmp, "w"))
        self.assertIsNotNone(self.asked(self.ev("PreToolUse", c, "t2", cwd=os.path.join(self.tmp, "w"))))
        self.assertEqual(self.ev("PreToolUse", c, "t3", cwd=self.tmp), "")  # another cwd
        with open(os.path.join(self.tmp, "w", "b.md"), "w") as g:
            g.write("two")
        self.assertEqual(self.ev("PreToolUse", c, "t4", cwd=os.path.join(self.tmp, "w")), "")  # another body
        self.assertEqual(self.ev("PreToolUse", "gh pr comment 13 --body-file b.md", "t5", cwd=os.path.join(self.tmp, "w")), "")

    def test_mcp_tool_calls_are_detected_and_keyed_on_input(self):
        n, a, b = "mcp__slack__post_message", {"channel": "#eng", "text": "hi"}, {"channel": "#eng", "text": "bye"}
        self.ev("PreToolUse", None, "t1", name=n, inp=a)
        self.ev("PostToolUse", None, "t1", name=n, inp=a)
        self.assertEqual(self.effects()[0]["rule"], "mcp:" + n)
        self.assertIsNotNone(self.asked(self.ev("PreToolUse", None, "t2", name=n, inp=a)))
        self.assertEqual(self.ev("PreToolUse", None, "t3", name=n, inp=b), "")

    def test_a_secret_in_the_command_is_kept_out_of_the_log_but_still_keys_the_resend(self):
        c = "curl -X POST -H 'Authorization: Bearer %s' https://api.example.com/v1/m" % GH
        self.assertEqual(self.ev("PreToolUse", c, "t1"), "")
        self.ev("PostToolUse", c, "t1")
        self.assertNotIn(GH, self.events().decode())
        self.assertEqual(self.steps(), ["planned", "begun", "sent"])
        self.assertIsNotNone(self.asked(self.ev("PreToolUse", c, "t2")))

    def test_declared_effect_is_not_recorded_twice_and_a_sent_one_guards_resends(self):
        i = self.plan("--how", "gh pr merge 4 --squash", target="git:origin/main")
        self.ok("effect", "begin", i)
        self.assertEqual(self.ev("PreToolUse", "gh pr merge 4 --squash", "t1"), "")
        self.ev("PostToolUse", "gh pr merge 4 --squash", "t1")
        self.assertEqual({r["id"] for r in self.effects()}, {i})
        self.assertEqual(self.state_of(i), "begun")  # only the sender marks a declared effect
        self.ok("effect", "mark", i, "sent")
        self.assertIn(i, self.asked(self.ev("PreToolUse", "gh pr merge 4 --squash", "t2")))
        self.assertEqual({r["id"] for r in self.effects()}, {i})

    def test_owner_rules_file(self):
        os.makedirs(os.path.join(self.tmp, "cfg", "awt"))
        with open(os.path.join(self.tmp, "cfg", "awt", "outbound"), "w") as g:
            g.write("# mine\n\n^deploy\\.sh \\S+\n([unclosed\n")
        self.ev("PreToolUse", "./deploy.sh prod", "t0")
        self.assertEqual(self.effects(), [])  # ^ anchors at the command start; './' is not 'deploy.sh'
        self.ev("PreToolUse", "deploy.sh prod", "t1")
        self.assertTrue(self.effects()[0]["rule"].startswith("owner:"))

    def test_plugin_shape_and_hook_silence(self):
        out = self.hook({"phase": "before", "tool": "Bash", "command": "gh pr merge 4", "cwd": self.cwd, "id": "perm-1"}, by="agt_1")
        self.assertEqual(out, "")
        self.assertEqual(self.effects()[0]["by"], "agt_1")
        self.hook({"phase": "after", "tool": "Bash", "command": "gh pr merge 4", "cwd": self.cwd, "id": "call-9", "ok": True}, by="agt_1")
        self.assertEqual(self.steps(), ["planned", "begun", "sent"])  # paired by key, the ids differ
        self.assertIsNotNone(self.asked(self.hook({"phase": "before", "tool": "Bash", "command": "gh pr merge 4", "cwd": self.cwd, "id": "perm-2"})))
        self.hook({"phase": "after", "tool": "Bash", "command": "gh pr merge 4", "cwd": self.cwd, "id": "call-9", "ok": True})  # replay
        self.assertEqual(self.steps(), ["planned", "begun", "sent"])
        n = self.events()
        for junk in ["", "not json", "[]", "{}", '{"hook_event_name": 5}', '{"phase": "before"}', '{"phase":"before","tool":"Bash","command":["x"]}']:
            self.assertEqual(self.hook(None, stdin=junk), "")
        self.assertEqual(self.hook({"phase": "before", "tool": "Bash", "command": "git push"}, root=os.path.join(self.tmp, "no-such-task")), "")
        self.assertEqual(self.events(), n)

    def test_session_end_hook_still_reads_no_stdin(self):
        r = self.awt("ingest", "--source", "claude", "--hook", input=json.dumps({"hook_event_name": "PreToolUse"}), root="")
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_awt_never_runs_what_it_detects(self):
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        canary = os.path.join(self.tmp, "ran")
        for n in ("git", "gh", "curl", "npm"):
            with open(os.path.join(bindir, n), "w") as g:
                g.write("#!/bin/sh\necho %s >> %s\n" % (n, canary))
            os.chmod(os.path.join(bindir, n), 0o755)
        self.env["PATH"] = bindir + os.pathsep + self.env["PATH"]
        for c in ["git push", "gh pr create", "curl -X POST https://api.example.com", "npm publish"]:
            self.ev("PreToolUse", c, "t" + c[:3])
            self.ev("PostToolUse", c, "t" + c[:3])
        self.assertFalse(os.path.exists(canary))
        self.assertEqual(len(self.effects()), 12)

    def test_detected_rows_reach_the_store_and_the_brief(self):
        self.env["AWT_STORE"] = os.path.join(self.tmp, "store")
        self.ev("PreToolUse", "git push origin x", "t1")
        out = self.ok("resume").stdout
        self.assertIn("begun", out)
        self.ok("ingest", "--rebuild")
        import sqlite3
        db = sqlite3.connect(os.path.join(self.tmp, "store", "store.db"))
        row = db.execute("SELECT origin, rule, state, tool_call_id FROM effects").fetchall()
        self.assertEqual(row, [("detected", "git push", "begun", "t1")])
        self.ev("PostToolUse", "git push origin x", "t1", model="claude-sonnet-5-5")  # a later row lands through the incremental sync, no --rebuild
        self.ok("ingest")
        self.assertEqual(db.execute("SELECT state FROM effects").fetchall(), [("sent",)])
        self.assertEqual(db.execute("SELECT model FROM records WHERE type='effect' ORDER BY rowid DESC LIMIT 1").fetchone(), ("claude-sonnet-5-5",))

    def test_init_writes_the_tool_hooks(self):
        s = json.loads(slurp(self.p(".claude", "settings.json")))
        for ev in ("PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionDenied"):
            g = s["hooks"][ev][0]
            self.assertEqual(g["matcher"], "Bash|mcp__.*|Agent|Task")
            self.assertTrue(g["hooks"][0]["command"].endswith("awt ingest --event --hook"), ev)
            self.assertEqual(g["hooks"][0]["timeout"], 10)
        self.assertIn("SessionEnd", s["hooks"])


def keys(cmd, cwd="/w", tool="Bash", inp=None):
    return [k for _r, _t, k in MOD.classify(tool, inp if inp is not None else {"command": cmd}, cwd)]


class ClassifyP3(unittest.TestCase):
    """M4/M5: the pattern gaps the phase 3 review found."""

    def test_missed_forms_now_match(self):
        want = {
            "gh -R owner/parsekit pr comment 12 --body x": "gh pr comment", "gh --repo owner/parsekit issue create --title t": "gh issue create",
            "gh pr comment 12 \\\n  --body x": "gh pr comment", "git \\\n push": "git push", "echo hi # note\ngit push": "git push",
            "git push # now": "git push", "bash -lc 'git push origin main'": "git push", "sh -ec 'gh pr create'": "gh pr create",
            "curl -sX POST https://api.example.com/x": "curl POST", "curl -sd '{}' https://api.example.com/x": "curl POST",
            "scp notes.txt deploy@build.example.com:": "scp", "gh api repos/o/r/issues --raw-field=title=x": "gh api POST",
            "gh api graphql -f query='mutation { addComment(input: {}) { clientMutationId } }'": "gh api POST",
            "gh workflow run ci.yml": "gh workflow run",
        }
        for cmd, rule in want.items():
            with self.subTest(cmd=cmd):
                self.assertEqual(matched(cmd), [rule])

    def test_reads_and_quoted_hashes_do_not_match(self):
        for cmd in ["gh api graphql -f query='{ viewer { login } }'", "echo 'a # git push'", "echo \"x\" # git push", "curl -sS https://example.com",
                    "git log --oneline # git push"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(matched(cmd), [])

    def test_mcp_reads_are_not_sends_and_missed_sends_are(self):
        for t in ["mcp__x__get_posts", "mcp__x__list_comments", "mcp__x__search_posts", "mcp__x__get_comment", "mcp__x__read_message", "mcp__x__fetch_issue"]:
            self.assertEqual(MOD.classify(t, {"q": 1}, "/w"), [], t)
        for t in ["mcp__github__push_files", "mcp__github__merge_pull_request", "mcp__github__create_issue", "mcp__x__reply_to_thread", "mcp__mail__sendEmail"]:
            self.assertEqual(len(MOD.classify(t, {"q": 1}, "/w")), 1, t)

    def test_heredoc_bodies_are_in_the_key_but_never_match(self):
        a = "gh pr comment 12 --body \"$(cat <<'EOF'\none\nEOF\n)\""
        b = a.replace("one", "two")
        self.assertEqual(matched(a), ["gh pr comment"])
        self.assertNotEqual(keys(a), keys(b))
        self.assertEqual(keys(a), keys(a))
        self.assertEqual(matched("cat <<EOF\ngit push\nEOF"), [])

    def test_git_push_key_follows_head_and_publish_key_the_version(self):
        import tempfile
        d = tempfile.mkdtemp(prefix="awt-test-")
        self.addCleanup(__import__("shutil").rmtree, d, True)
        os.makedirs(os.path.join(d, ".git", "refs", "heads"))
        open(os.path.join(d, ".git", "HEAD"), "w").write("ref: refs/heads/main\n")
        ref = os.path.join(d, ".git", "refs", "heads", "main")
        open(ref, "w").write("a" * 40 + "\n")
        k1 = keys("git push", d)
        self.assertEqual(k1, keys("git push", d))
        open(ref, "w").write("b" * 40 + "\n")
        self.assertNotEqual(k1, keys("git push", d))
        os.remove(ref)  # packed refs
        open(os.path.join(d, ".git", "packed-refs"), "w").write("# pack\n%s refs/heads/main\n" % ("c" * 40))
        self.assertNotEqual(keys("git push", d), k1)
        self.assertEqual(MOD.git_head(d, []), "c" * 40)
        open(os.path.join(d, "package.json"), "w").write('{"name": "parsekit", "version": "1.0.0"}')
        p1 = keys("npm publish", d)
        open(os.path.join(d, "package.json"), "w").write('{"name": "parsekit", "version": "1.0.1"}')
        self.assertNotEqual(p1, keys("npm publish", d))

    def test_redact_each_credential_form(self):
        pw = "hunter" + "2pass"
        for cmd in ["curl -u bob:%s -X POST https://api.example.com/x" % pw, "curl -ubob:%s -X POST https://api.example.com/x" % pw,
                    "curl --user bob:%s -d a=1 https://api.example.com/x" % pw, "curl -X POST https://bob:%s@api.example.com/x" % pw,
                    "curl -X POST -H 'Authorization: Basic %s' https://api.example.com/x" % pw, "curl -X POST -H 'authorization: Bearer %s' https://api.example.com/x" % pw,
                    "curl -X POST -H 'X-Api-Key: %s' https://api.example.com/x" % pw, "curl -X POST --oauth2-bearer %s https://api.example.com/x" % pw,
                    "curl -X POST --password=%s https://api.example.com/x" % pw, "curl -X POST --token %s https://api.example.com/x" % pw,
                    "gh api -X POST repos/o/r/issues -f 'title=t' --header 'Authorization: token %s'" % pw]:
            with self.subTest(cmd=cmd):
                r = MOD.redact(MOD.classify("Bash", {"command": cmd}, "/w")[0][1])
                self.assertNotIn(pw, r)
                self.assertIn("[REDACTED]", r)
        self.assertEqual(MOD.redact("git push -u origin main"), "git push -u origin main")  # -u is only a password flag for curl
        self.assertNotIn(pw, MOD.redact('mcp__x__post {"password": "%s", "text": "hi"}' % pw))


class DetectP3(DetectBase):
    def repo(self, sha="a" * 40):
        os.makedirs(os.path.join(self.tmp, "repo", ".git", "refs", "heads"), exist_ok=True)
        with open(os.path.join(self.tmp, "repo", ".git", "HEAD"), "w") as g:
            g.write("ref: refs/heads/main\n")
        self.head(sha)
        return os.path.join(self.tmp, "repo")

    def head(self, sha):
        with open(os.path.join(self.tmp, "repo", ".git", "refs", "heads", "main"), "w") as g:
            g.write(sha + "\n")

    def send(self, cmd, cid, cwd=None, **kw):
        out = self.ev("PreToolUse", cmd, cid, cwd=cwd, **kw)
        if not out:
            self.ev("PostToolUse", cmd, cid, cwd=cwd, **kw)
        return out

    def test_h1_repeat_push_with_a_commit_between_never_asks_and_rows_stay_distinct(self):
        d = self.repo()
        self.assertEqual(self.send("git push", "p1", d), "")
        self.head("b" * 40)
        self.assertEqual(self.send("git push", "p2", d), "")
        self.assertEqual(len({r["id"] for r in self.effects()}), 2)
        self.assertEqual(len({r["key"] for r in self.effects() if r["step"] == "planned"}), 2)
        self.assertEqual(self.send("git push", "p3", d), "")  # same head, a plain resend: harmless, still no ask
        self.assertEqual(len({r["id"] for r in self.effects()}), 3)

    def test_h1_force_push_ssh_rsync_scp_and_publish(self):
        d = self.repo()
        for c in ["ssh deploy@build.example.com uptime", "rsync -a out/ build.example.com:/srv/", "scp a.tgz deploy@build.example.com:/srv"]:
            self.assertEqual(self.send(c, "i1", d), "", c)
            self.assertEqual(self.send(c, "i2", d), "", c)
        self.assertEqual(self.send("git push --force-with-lease", "f1", d), "")
        self.assertIsNotNone(self.asked(self.ev("PreToolUse", "git push --force-with-lease", "f2", cwd=d)))
        with open(os.path.join(d, "package.json"), "w") as g:
            g.write('{"name": "parsekit", "version": "1.0.0"}')
        self.assertEqual(self.send("npm publish", "n1", d), "")
        self.assertIsNotNone(self.asked(self.ev("PreToolUse", "npm publish", "n2", cwd=d)))  # the same version again
        with open(os.path.join(d, "package.json"), "w") as g:
            g.write('{"name": "parsekit", "version": "1.0.1"}')
        self.assertEqual(self.ev("PreToolUse", "npm publish", "n3", cwd=d), "")  # a bumped version is a new send

    def test_h2_a_second_heredoc_comment_is_not_a_resend(self):
        c = "gh pr comment 12 --body \"$(cat <<'EOF'\n%s\nEOF\n)\""
        self.send(c % "round one", "h1")
        self.assertEqual(self.ev("PreToolUse", c % "round two", "h2"), "")
        self.assertIsNotNone(self.asked(self.ev("PreToolUse", c % "round one", "h3")))

    def test_h3_a_replayed_settled_id_does_not_settle_another_open_effect(self):
        w = lambda ph, i: self.hook({"phase": ph, "tool": "Bash", "command": "git push origin dev", "cwd": self.cwd, "id": i, "ok": True})
        w("before", "perm-1")
        w("before", "perm-2")
        w("after", "call-9")  # settles the first
        before = [self.state_of(i) for i in sorted({r["id"] for r in self.effects()})]
        self.assertEqual(sorted(before), ["begun", "sent"])
        w("after", "call-9")  # replayed
        self.assertEqual(sorted(self.state_of(i) for i in {r["id"] for r in self.effects()}), ["begun", "sent"])
        self.assertEqual(len([r for r in self.effects() if r.get("tool_call_id") == "call-9"]), 1)

    def test_h4_credentials_never_reach_the_log(self):
        pw = "hunter" + "2pass"
        for n, c in enumerate(["curl -u bob:%s -X POST https://bob:%s@api.example.com/x" % (pw, pw), "curl -X POST -H 'X-Api-Key: %s' https://api.example.com/x" % pw,
                               "curl -X POST --password=%s https://api.example.com/x" % pw]):
            self.send(c, "c%d" % n)
        self.assertNotIn(pw, self.events().decode())
        self.assertIn("[REDACTED]", self.events().decode())
        self.assertIsNotNone(self.asked(self.ev("PreToolUse", "curl -X POST --password=%s https://api.example.com/x" % pw, "c9")))  # the key is the unredacted command

    def test_m1_a_denied_call_is_not_sent_and_does_not_block_done(self):
        self.ev("PreToolUse", "gh pr merge 4 --squash", "t1")
        self.ev("PermissionDenied", "gh pr merge 4 --squash", "t1")
        i = self.effects()[0]["id"]
        self.assertEqual(self.state_of(i), "planned")
        self.ok("status", "done")  # a denied detected effect is not an open question
        self.ev("PermissionDenied", "gh pr merge 4 --squash", "t1")  # replay: nothing more
        self.assertEqual(self.steps(), ["planned", "begun", "planned"])
        self.assertEqual(self.ev("PreToolUse", "gh pr merge 4 --squash", "t2"), "")  # asking again is fine: it was never sent
        self.ev("PostToolUse", "gh pr merge 4 --squash", "t2")
        self.assertEqual(sorted(self.state_of(x) for x in {r["id"] for r in self.effects()}), ["planned", "sent"])
        self.assertNotRegex(self.awt("doctor").stdout, r"warn \d+ quarantined")

    def test_m1_plugin_denied_phase_and_a_failed_exit_stays_unknown(self):
        self.hook({"phase": "before", "tool": "Bash", "command": "git push origin dev", "cwd": self.cwd, "id": "perm-1"})
        self.hook({"phase": "denied", "tool": "Bash", "command": "git push origin dev", "cwd": self.cwd, "id": "perm-1"})
        self.assertEqual(self.state_of(self.effects()[0]["id"]), "planned")
        self.ev("PreToolUse", "gh pr create", "t5")
        self.ev("PostToolUseFailure", "gh pr create", "t5")
        j = [r for r in self.effects() if r.get("rule") == "gh pr create"][0]["id"]
        self.assertEqual(self.state_of(j), "unknown")
        self.bad("status", "done")

    def test_m2_mark_not_sent_then_the_next_call_is_not_quarantined(self):
        self.ev("PreToolUse", "gh pr create", "t1")
        self.ev("PostToolUseFailure", "gh pr create", "t1")
        i = self.effects()[0]["id"]
        self.ok("effect", "mark", i, "not-sent", "--why", "it failed")
        self.ev("PostToolUse", "gh pr create", "t2")  # only the result is seen: it settles the planned effect
        self.assertEqual(self.state_of(i), "sent")
        self.assertNotRegex(self.awt("doctor").stdout, r"warn \d+ quarantined")

    def test_m8_a_held_lock_means_nothing_is_recorded_and_exit_zero(self):
        fd = os.open(self.p(".awt", "events.jsonl"), os.O_RDONLY)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            t = time.time()
            self.assertEqual(self.ev("PreToolUse", "git push", "t1"), "")
            self.assertLess(time.time() - t, 8)
        finally:
            os.close(fd)
        self.assertEqual(self.effects(), [])

    def test_m8_a_batch_reads_the_log_once(self):
        evs = [{"phase": "after", "tool": "Bash", "command": "git push origin b%d" % n, "cwd": self.cwd, "id": "c%d" % n, "ok": True} for n in range(30)]
        self.hook(evs)
        self.assertEqual(len([r for r in self.effects() if r["step"] == "sent"]), 30)

    def test_m7_the_hook_command_skips_awt_for_calls_that_cannot_be_outbound(self):
        bindir = os.path.join(self.tmp, "proj")
        os.makedirs(bindir)
        canary = os.path.join(self.tmp, "called")
        with open(os.path.join(bindir, "awt"), "w") as g:
            g.write("#!/bin/sh\necho x >> %s\ncat > /dev/null\n" % canary)
        os.chmod(os.path.join(bindir, "awt"), 0o755)
        cmd = json.loads(slurp(self.p(".claude", "settings.json")))["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        env = dict(self.env, CLAUDE_PROJECT_DIR=bindir, PATH=bindir + os.pathsep + self.env["PATH"], XDG_CONFIG_HOME=os.path.join(self.tmp, "cfg"))
        run = lambda c: subprocess.run(["sh", "-c", cmd], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": c}}), text=True, env=env, capture_output=True)
        for c in ["ls -la", "git status", "cat README.md", "python3 -m unittest"]:
            self.assertEqual(run(c).returncode, 0)
        self.assertFalse(os.path.exists(canary))
        for c in ["git push origin main", "gh pr comment 3 --body x", "curl -X POST https://example.com", "npm publish"]:
            run(c)
        self.assertEqual(len(slurp(canary).split()), 4)
        os.makedirs(os.path.join(self.tmp, "cfg", "awt"))
        open(os.path.join(self.tmp, "cfg", "awt", "outbound"), "w").write("^deploy\n")  # an owner file: every call goes through
        run("ls -la")
        self.assertEqual(len(slurp(canary).split()), 5)


class FixtureSession(Base):
    """M9: a recorded parsekit session driven through `ingest --event --hook` in order."""

    def test_parsekit_session_end_to_end(self):
        self.init()
        self.env["XDG_CONFIG_HOME"] = os.path.join(self.tmp, "cfg")
        d = os.path.join(self.tmp, "parsekit")
        os.makedirs(os.path.join(d, ".git", "refs", "heads"))
        open(os.path.join(d, ".git", "HEAD"), "w").write("ref: refs/heads/feat/lexer\n")
        os.makedirs(os.path.join(d, ".git", "refs", "heads", "feat"))
        ref = os.path.join(d, ".git", "refs", "heads", "feat", "lexer")
        open(ref, "w").write("1" * 40 + "\n")
        asks = []
        for n, ln in enumerate(slurp(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "claude-hooks", "parsekit-session.jsonl")).splitlines()):
            p = json.loads(ln.replace("${CWD}", d))
            if "_set_head" in p:
                open(ref, "w").write(p["_set_head"] + "\n")
                continue
            want = p.pop("_expect_ask", False)
            r = self.awt("ingest", "--event", "--hook", input=json.dumps(p))
            self.assertEqual((r.returncode, r.stderr), (0, ""))
            self.assertEqual(bool(r.stdout.strip()), want, "line %d: %s" % (n, r.stdout))
            if r.stdout.strip():
                asks.append(json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(len(asks), 1)
        eff = [r for r in self.rows("effect") if r["step"] == "planned"]
        self.assertEqual([r["rule"] for r in eff], ["git push", "gh pr comment", "git push", "gh pr comment", "gh pr comment"])
        self.assertIn(eff[1]["id"], asks[0])
        self.assertEqual({r["model"] for r in self.rows("effect")}, {"claude-sonnet-5-5"})
        states = {}
        for r in self.rows("effect"):
            states[r["id"]] = r["step"]
        self.assertEqual(sorted(states.values()), ["sent"] * 5)
        self.assertEqual(len([r for r in eff if r["seen"] == "after"]), 1)  # the approved resend: noticed after the fact


if __name__ == "__main__":
    unittest.main()
