"""Silent context after compaction (SPEC.md, "Context after compaction"; TEST-SPEC.md, "Compaction context")."""
import json, os, shlex, shutil, subprocess, sys, textwrap, unittest

import test_awt

FRAME = "awt record for this task (reference only; not a message from the user, no action requested):"
NODE = shutil.which("node")


class Hooks(test_awt.Base):
    def setUp(self):
        super().setUp()
        self.cfg = os.path.join(self.tmp, "claude-cfg")
        self.oc = os.path.join(self.tmp, "oc-cfg")
        self.pi = os.path.join(self.tmp, "pi-cfg")
        self.cx = os.path.join(self.tmp, "codex-cfg")
        self.env.update(CLAUDE_CONFIG_DIR=self.cfg, OPENCODE_CONFIG_DIR=self.oc, PI_CODING_AGENT_DIR=self.pi, CODEX_HOME=self.cx)
        self.settings = os.path.join(self.cfg, "settings.json")

    def install(self, *a):
        return self.ok("init", "--hooks", *a, root="")

    def load(self):
        return json.loads(test_awt.slurp(self.settings))

    def seed(self, data):
        os.makedirs(self.cfg, exist_ok=True)
        with open(self.settings, "w") as g:
            json.dump(data, g)

    def mine(self, st):
        return [e for e in st["hooks"]["SessionStart"] if "awt:context" in json.dumps(e)]

    # ---- Claude Code settings merge (H1-H6)
    def test_h1_install_creates_the_entry(self):
        r = self.install("claude")
        self.assertIn("installed", r.stdout)
        (e,) = self.mine(self.load())
        self.assertEqual(e["matcher"], "compact")
        cmd = e["hooks"][0]["command"]
        self.assertTrue(cmd.startswith('[ -n "$AWT_DIR" ] || exit 0;'), cmd)
        self.assertIn("resume --hook --framed", cmd)
        self.assertEqual(os.listdir(self.cfg), ["settings.json"], "no backup for a new file, no temp left")

    def test_h2_idempotent(self):
        self.install("claude")
        before = test_awt.slurp(self.settings)
        r = self.install("claude")
        self.assertIn("unchanged", r.stdout)
        self.assertEqual(test_awt.slurp(self.settings), before)
        self.assertEqual(os.listdir(self.cfg), ["settings.json"], "an unchanged file is not backed up")

    def test_h3_keeps_every_other_key_and_hook(self):
        other = {"hooks": [{"type": "command", "command": "echo mine"}]}
        self.seed({"model": "x", "permissions": {"allow": ["Bash(ls)"]},
                   "hooks": {"SessionStart": [other], "PreToolUse": [{"matcher": "Bash", "hooks": []}]}})
        self.install("claude")
        st = self.load()
        self.assertEqual(st["model"], "x")
        self.assertEqual(st["permissions"], {"allow": ["Bash(ls)"]})
        self.assertEqual(st["hooks"]["PreToolUse"], [{"matcher": "Bash", "hooks": []}])
        self.assertEqual(st["hooks"]["SessionStart"][0], other)
        self.assertEqual(len(self.mine(st)), 1)

    def test_h4_backup_of_the_old_file(self):
        self.seed({"model": "x"})
        old = test_awt.slurp(self.settings)
        r = self.install("claude")
        baks = [x for x in os.listdir(self.cfg) if ".awt-bak-" in x]
        self.assertEqual(len(baks), 1)
        self.assertEqual(test_awt.slurp(os.path.join(self.cfg, baks[0])), old)
        self.assertIn(baks[0], r.stdout)

    def test_h5_uninstall_removes_only_ours(self):
        other = {"hooks": [{"type": "command", "command": "echo mine"}]}
        self.seed({"hooks": {"SessionStart": [other]}, "model": "x"})
        self.install("claude")
        r = self.ok("init", "--hooks", "claude", "--uninstall", root="")
        self.assertIn("removed", r.stdout)
        self.assertEqual(self.load(), {"hooks": {"SessionStart": [other]}, "model": "x"})

    def test_h5b_uninstall_leaves_no_empty_husk_and_is_idempotent(self):
        self.seed({"model": "x"})
        self.install("claude")
        self.ok("init", "--hooks", "claude", "--uninstall", root="")
        self.assertEqual(self.load(), {"model": "x"})
        self.assertIn("absent", self.ok("init", "--hooks", "claude", "--uninstall", root="").stdout)

    def test_h6_refuses_a_file_it_cannot_parse(self):
        os.makedirs(self.cfg)
        with open(self.settings, "w") as g:
            g.write("{ not json")
        r = self.bad("init", "--hooks", "claude", root="")
        self.assertIn("fix:", r.stderr)
        self.assertEqual(test_awt.slurp(self.settings), "{ not json")
        self.assertEqual(os.listdir(self.cfg), ["settings.json"])

    def test_h6b_a_moved_awt_updates_the_entry(self):
        self.install("claude")
        st = self.load()
        self.mine(st)[0]["hooks"][0]["command"] = "/old/place/awt resume --hook --framed # awt:context"
        self.seed(st)
        self.assertIn("updated", self.install("claude").stdout)
        (e,) = self.mine(self.load())
        self.assertNotIn("/old/place", json.dumps(e))

    def test_h7_never_writes_the_real_home(self):
        self.install("all")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".claude")), "HOME is the temp dir; only the config dirs are used")
        for d in (self.cfg, self.oc, self.pi):
            self.assertTrue(os.path.isdir(d), d)

    def test_h8_flags_stand_alone(self):
        self.bad("init", "--hooks", "claude", "--goal", "g", "--done", "d", root="", code=2)
        self.bad("init", "--uninstall", root="", code=2)

    # ---- the AWT_DIR gate and the framing line (G1-G4)
    def hook_cmd(self):
        self.install("claude")
        return self.mine(self.load())[0]["hooks"][0]["command"]

    def run_hook(self, cmd, awt_dir=None, cwd=None):
        env = dict(self.env)
        env.pop("AWT_DIR", None)
        if awt_dir:
            env["AWT_DIR"] = awt_dir
        return subprocess.run(["sh", "-c", cmd], capture_output=True, text=True, env=env, cwd=cwd or self.tmp)

    def test_g1_prints_nothing_without_awt_dir_even_inside_a_task(self):
        self.init()
        cmd = self.hook_cmd()
        r = self.run_hook(cmd, cwd=self.root)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_g2_prints_frame_then_the_plain_brief_with_awt_dir(self):
        self.init()
        self.ok("decide", "token-zq41", "--why", "test")
        self.ok("state", "--now", "doing x", "--next", "then y")
        r = self.run_hook(self.hook_cmd(), awt_dir=self.root)
        self.assertEqual(r.returncode, 0)
        first, rest = r.stdout.split("\n", 1)
        self.assertEqual(first, FRAME)
        self.assertEqual(rest, self.ok("resume").stdout.replace("./awt list | ./awt find <term>\n", ""), "the plain brief minus its command pointers")
        low = r.stdout.lower()
        for bad in ("carry on", "continue", "reply", "please", "you should"):
            self.assertNotIn(bad, low.split("\n", 1)[0], bad)
        self.assertNotIn("carry on", low)

    def test_g3_framed_brief_fits_the_budget_plus_the_frame_line(self):
        self.init()
        for i in range(60):
            self.ok("decide", "choice-%02d %s" % (i, "x" * 250), "--why", "y" * 250, "--tag", "rule")
            self.ok("ask", "question-%02d %s" % (i, "q" * 350))
        r = self.run_hook(self.hook_cmd(), awt_dir=self.root)
        self.assertLessEqual(len(r.stdout), 4400 + len(FRAME) + 1)

    def test_g9_framed_brief_keeps_the_newest_notes(self):
        self.init()
        for i in range(8):
            self.ok("note", "fact-%d" % i)
        self.ok("note", "long " + "w" * 250)
        out = self.run_hook(self.hook_cmd(), awt_dir=self.root).stdout
        self.assertIn("## Recent notes", out)
        sec = out.split("## Recent notes\n", 1)[1].split("\n## ", 1)[0].splitlines()
        self.assertEqual(len(sec), 5, sec)
        self.assertTrue(sec[0].startswith("long ") and len(sec[0]) <= 100, sec[0])
        self.assertEqual(sec[1:], ["fact-7", "fact-6", "fact-5", "fact-4"])
        self.assertNotIn("fact-3", out)
        self.assertNotIn("Recent notes", self.ok("resume").stdout, "the plain brief is unchanged")

    def test_g9b_notes_stay_inside_the_total_at_max_fill(self):
        self.init()
        self.ok("state", "--now", "n" * 700, "--next", "x" * 300)
        for i in range(60):
            self.ok("decide", "choice-%02d %s" % (i, "x" * 250), "--why", "y" * 250, "--tag", "rule")
            self.ok("ask", "question-%02d %s" % (i, "q" * 350))
            self.ok("note", "note-%02d %s" % (i, "z" * 250))
        r = self.run_hook(self.hook_cmd(), awt_dir=self.root)
        self.assertLessEqual(len(r.stdout), 4400 + len(FRAME) + 1)
        self.assertIn("## Recent notes", r.stdout)

    def test_g4_silent_when_the_node_is_gone_or_awt_is_missing(self):
        self.init()
        self.ok("decide", "token-zq41", "--why", "test")
        cmd = self.hook_cmd()
        self.assertIn("token-zq41", self.run_hook(cmd, awt_dir=self.root).stdout, "the unreplaced command prints")
        r = self.run_hook(cmd, awt_dir=os.path.join(self.tmp, "nowhere"))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        gone = cmd.replace(shlex.quote(test_awt.AWT), "/no/such/awt")
        self.assertNotEqual(gone, cmd)
        r = self.run_hook(gone, awt_dir=self.root)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_g5_framed_needs_hook(self):
        self.init()
        self.bad("resume", "--framed", code=2)

    def test_g6_plain_hook_output_is_unchanged(self):
        self.init()
        self.assertEqual(self.ok("resume", "--hook").stdout, self.ok("resume").stdout)

    def test_g7_framed_leaves_no_brief_file_and_no_imperative_hints(self):
        self.init()
        bf = self.p("BRIEF.md")
        if os.path.exists(bf):
            os.remove(bf)
        r = self.run_hook(self.hook_cmd(), awt_dir=self.root)
        self.assertFalse(os.path.exists(bf), "framed mode must not rebuild BRIEF.md after printing")
        for hint in ("Before stopping", "No handoff yet", "./awt state", "./awt init"):
            self.assertNotIn(hint, r.stdout)
        self.assertIn("No handoff yet", self.ok("resume").stdout, "the plain brief keeps its hint")

    def test_g8_framed_effects_are_facts_not_next_steps(self):
        self.init()
        self.write("outbox/n.md")
        out = self.ok("effect", "plan", "--target", "slack:#eng", "--body", "outbox/n.md", "--how", "post").stdout
        self.assertIn("effect begin", self.ok("resume").stdout)
        r = self.run_hook(self.hook_cmd(), awt_dir=self.root)
        self.assertIn("slack:#eng", r.stdout, out)
        self.assertNotIn("effect begin", r.stdout)
        self.assertNotIn("effect mark", r.stdout)

    # ---- install merge edge cases (M1, M2, M3, L1, L2, L8)
    def test_m1_symlinked_settings_is_followed_and_mode_kept(self):
        real = os.path.join(self.tmp, "dotfiles", "settings.json")
        os.makedirs(os.path.dirname(real))
        os.makedirs(self.cfg)
        with open(real, "w") as g:
            json.dump({"model": "x"}, g)
        os.chmod(real, 0o640)
        os.symlink(real, self.settings)
        self.install("claude")
        self.assertTrue(os.path.islink(self.settings), "the link stays a link")
        self.assertEqual(os.path.realpath(self.settings), real)
        st = json.loads(test_awt.slurp(real))
        self.assertEqual(st["model"], "x")
        self.assertEqual(len(self.mine(st)), 1)
        self.assertEqual(os.stat(real).st_mode & 0o777, 0o640)
        self.ok("init", "--hooks", "claude", "--uninstall", root="")
        self.assertTrue(os.path.islink(self.settings))
        self.assertEqual(json.loads(test_awt.slurp(real)), {"model": "x"})

    def test_m2_mixed_entry_keeps_the_sibling_hook(self):
        mine = {"type": "command", "command": "x # awt:context"}
        mix = {"matcher": "", "hooks": [{"type": "command", "command": "echo mine"}, mine]}
        self.seed({"hooks": {"SessionStart": [mix]}})
        self.install("claude")
        ss = self.load()["hooks"]["SessionStart"]
        self.assertIn({"matcher": "", "hooks": [{"type": "command", "command": "echo mine"}]}, ss)
        self.assertEqual(len(self.mine({"hooks": {"SessionStart": ss}})), 1)
        self.assertEqual(sum("echo mine" in json.dumps(e) for e in ss), 1)
        self.assertNotIn('"x # awt:context"', json.dumps(ss))
        self.assertIn("unchanged", self.install("claude").stdout)
        self.ok("init", "--hooks", "claude", "--uninstall", root="")
        self.assertEqual(self.load(), {"hooks": {"SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": "echo mine"}]}]}})

    def test_m3_pinned_path_is_the_invoked_path_not_a_resolved_symlink(self):
        link = os.path.join(self.tmp, "bin", "awt")
        os.makedirs(os.path.dirname(link))
        os.symlink(test_awt.AWT, link)
        r = subprocess.run([sys.executable, "-I", link, "init", "--hooks", "claude"], capture_output=True, text=True, env=self.env, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        cmd = self.mine(self.load())[0]["hooks"][0]["command"]
        self.assertIn(shlex.quote(link), cmd)

    def test_m3_doctor_flags_a_pinned_awt_that_is_gone(self):
        os.makedirs(self.oc)
        self.install("all")
        self.assertTrue(all(x.startswith("ok ") for x in self.doctor_lines()))
        for p in (self.settings, os.path.join(self.cx, "hooks.json"), os.path.join(self.oc, "plugins", "awt-context.js"), os.path.join(self.pi, "extensions", "awt-context.ts")):
            test = test_awt.slurp(p)
            with open(p, "w") as g:
                g.write(test.replace(shlex.quote(test_awt.AWT) if p.endswith(".json") else json.dumps(test_awt.AWT), "/no/such/awt" if p.endswith(".json") else '"/no/such/awt"'))
        lines = self.doctor_lines()
        self.assertEqual(len(lines), 4, lines)
        self.assertTrue(all(x.startswith("warn ") and "/no/such/awt" in x and "ask the person" in x for x in lines), lines)

    def test_l1_backups_do_not_overwrite_each_other_and_are_pruned(self):
        self.seed({"model": "x"})
        first = test_awt.slurp(self.settings)
        self.install("claude")
        self.ok("init", "--hooks", "claude", "--uninstall", root="")
        baks = sorted(os.listdir(self.cfg))
        baks = [b for b in baks if ".awt-bak-" in b]
        self.assertEqual(len(baks), 2, "two runs in the same second keep two backups")
        self.assertIn(first, [test_awt.slurp(os.path.join(self.cfg, b)) for b in baks])
        for _ in range(8):
            self.install("claude")
            self.ok("init", "--hooks", "claude", "--uninstall", root="")
        self.assertLessEqual(len([b for b in os.listdir(self.cfg) if ".awt-bak-" in b]), 5)

    def test_l2_awt_writers_take_turns(self):
        import fcntl, time
        self.seed({"model": "x"})
        fd = os.open(self.cfg, os.O_RDONLY)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            p = subprocess.Popen([sys.executable, "-I", test_awt.AWT, "init", "--hooks", "claude"], env=self.env, cwd=self.tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            time.sleep(1.0)
            self.assertIsNone(p.poll(), "an awt writer waits while another holds the lock")
            self.assertNotIn("hooks", self.load())
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        out, err = p.communicate(timeout=30)
        self.assertEqual(p.returncode, 0, err)
        self.assertEqual(len(self.mine(self.load())), 1)

    def test_l2b_concurrent_installs_and_uninstalls_leave_one_valid_file(self):
        self.seed({"model": "x", "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}})
        procs = [subprocess.Popen([sys.executable, "-I", test_awt.AWT, "init", "--hooks", "claude"] + (["--uninstall"] if i % 3 == 2 else []),
                                  env=self.env, cwd=self.tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(12)]
        for p in procs:
            out, err = p.communicate(timeout=60)
            self.assertEqual(p.returncode, 0, err)
        st = self.load()
        self.assertEqual(st["model"], "x")
        self.assertIn("echo mine", json.dumps(st))
        self.assertLessEqual(len(self.mine(st)), 1)
        self.assertEqual([f for f in os.listdir(self.cfg) if "tmp" in f], [])

    def test_x1_codex_hook_is_the_same_entry_in_hooks_json(self):
        os.makedirs(self.cx)
        f = os.path.join(self.cx, "hooks.json")
        with open(f, "w") as g:
            json.dump({"description": "mine", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo s"}]}]}}, g)
        r = self.install("codex")
        self.assertIn("hooks codex: installed", r.stdout)
        st = json.loads(test_awt.slurp(f))
        self.assertEqual(st["description"], "mine")
        self.assertIn("Stop", st["hooks"])
        (e,) = self.mine(st)
        self.assertEqual(e["matcher"], "compact")
        self.assertIn("resume --hook --framed", e["hooks"][0]["command"])
        self.assertIn("unchanged", self.install("codex").stdout)
        self.assertTrue(any("codex compaction hook installed" in x for x in self.doctor_lines()))
        self.assertFalse(os.path.exists(self.settings), "claude settings untouched")
        self.ok("init", "--hooks", "codex", "--uninstall", root="")
        st = json.loads(test_awt.slurp(f))
        self.assertNotIn("SessionStart", st["hooks"])
        self.assertIn("Stop", st["hooks"])

    def test_l8_will_not_touch_a_foreign_plugin_file(self):
        f = os.path.join(self.oc, "plugins", "awt-context.js")
        os.makedirs(os.path.dirname(f))
        with open(f, "w") as g:
            g.write("export const Mine = 1\n")
        for args in (("opencode",), ("opencode", "--uninstall")):
            r = self.bad("init", "--hooks", *args, root="")
            self.assertIn("fix:", r.stderr)
        self.assertEqual(test_awt.slurp(f), "export const Mine = 1\n")

    def test_l7_doctor_survives_odd_settings(self):
        os.makedirs(self.cfg)
        for blob in (b"\xff\xfe\x00bad", b'{"hooks": {"SessionStart": 5}}', b'{"hooks": {"SessionStart": [5, null, {"hooks": 3}]}}'):
            with open(self.settings, "wb") as g:
                g.write(blob)
            r = self.awt("doctor", root="")
            self.assertNotIn("Traceback", r.stderr)
            self.assertTrue(any("claude compaction hook missing" in x for x in r.stdout.splitlines()), r.stdout)

    # ---- doctor (D1-D2)
    def test_d0_doctor_outside_a_task_reports_machine_checks_and_exits_0(self):
        r = self.ok("doctor", root="")
        self.assertIn("ok no task root here: per-node checks skipped", r.stdout)
        self.assertIn("--dir <node>", r.stdout)
        self.assertNotIn("fail", r.stdout)
        r = self.bad("doctor", "--dir", os.path.join(self.tmp, "nowhere"), root="")
        self.assertIn("fail no task root", r.stdout)

    def doctor_lines(self):
        r = self.awt("doctor", root="")
        return [x for x in r.stdout.splitlines() if "compaction hook" in x]

    def test_d1_doctor_warns_per_detected_provider_and_never_fails(self):
        os.makedirs(self.cfg)
        os.makedirs(os.path.join(self.pi))
        lines = self.doctor_lines()
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(all(x.startswith("warn ") for x in lines), lines)
        self.assertFalse(any("opencode" in x for x in lines), "an absent provider is not reported")
        r = self.awt("doctor", root="")
        self.assertFalse(any(x.startswith("fail") and "compaction" in x for x in r.stdout.splitlines()))

    def test_d2_doctor_ok_after_install(self):
        os.makedirs(self.oc)
        self.install("all")
        lines = self.doctor_lines()
        self.assertEqual(len(lines), 4, lines)
        self.assertTrue(all(x.startswith("ok ") for x in lines), lines)
        self.ok("init", "--hooks", "all", "--uninstall", root="")
        self.assertTrue(all(x.startswith("warn ") for x in self.doctor_lines()))


@unittest.skipUnless(NODE, "node is not installed")
class PluginFiles(test_awt.Base):
    """The opencode plugin and the pi extension, loaded by node against fake host objects (no model, no network)."""

    def setUp(self):
        super().setUp()
        self.oc = os.path.join(self.tmp, "oc")
        self.pi = os.path.join(self.tmp, "pi")
        self.env.update(OPENCODE_CONFIG_DIR=self.oc, PI_CODING_AGENT_DIR=self.pi)
        self.ok("init", "--hooks", "opencode", root="")
        self.ok("init", "--hooks", "pi", root="")
        self.init()
        self.ok("decide", "token-zq41", "--why", "test")
        self.script = os.path.join(self.tmp, "drive.mjs")

    def drive(self, body, awt_dir=True):
        with open(self.script, "w") as g:
            g.write(body)
        env = dict(self.env)
        env.pop("AWT_DIR", None)
        if awt_dir:
            env["AWT_DIR"] = self.root
        r = subprocess.run([NODE, "--experimental-strip-types", "--no-warnings", self.script], capture_output=True, text=True, env=env, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def oc_js(self, awt_dir):
        return textwrap.dedent("""
            import { AwtContext } from %s
            const h = await AwtContext({})
            const out = { context: [] }
            await h["experimental.session.compacting"]({ sessionID: "s" }, out)
            console.log(JSON.stringify({ context: out.context, keys: Object.keys(h) }))
        """) % json.dumps("file://" + os.path.join(self.oc, "plugins", "awt-context.js"))

    def test_p1_opencode_adds_the_brief_to_the_compaction_context_only(self):
        res = self.drive(self.oc_js(True))
        self.assertEqual(res["keys"], ["experimental.session.compacting"], "no other hook: no autocontinue change, no message")
        (ctx,) = res["context"]
        self.assertTrue(ctx.startswith(FRAME + "\n"))
        self.assertIn("token-zq41", ctx)

    def test_p2_opencode_silent_without_awt_dir(self):
        self.assertEqual(self.drive(self.oc_js(False), awt_dir=False)["context"], [])

    def pi_js(self, branch):
        return textwrap.dedent("""
            import ext from %s
            const on = {}
            ext({ on: (n, f) => { on[n] = f } })
            const ev = () => ({ systemPromptOptions: { sections: {} } })
            const before = ev(); await on.before_agent_start(before)
            await on.session_start({}, { sessionManager: { getBranch: () => %s } })
            const resumed = ev(); await on.before_agent_start(resumed)
            await on.session_compact({})
            const after = ev(); await on.before_agent_start(after)
            const again = ev(); await on.before_agent_start(again)
            console.log(JSON.stringify({ names: Object.keys(on).sort(), before: before.systemPromptOptions.sections, resumed: resumed.systemPromptOptions.sections, after: after.systemPromptOptions.sections, again: again.systemPromptOptions.sections }))
        """) % (json.dumps("file://" + os.path.join(self.pi, "extensions", "awt-context.ts")), json.dumps(branch))

    def test_p3_pi_adds_a_system_section_only_after_a_compaction(self):
        res = self.drive(self.pi_js([]))
        self.assertEqual(res["names"], ["before_agent_start", "session_compact", "session_start"])
        self.assertEqual(res["before"], {})
        self.assertEqual(res["resumed"], {})
        sec = res["after"]["awt_record"]
        self.assertTrue(sec.startswith(FRAME + "\n"))
        self.assertIn("token-zq41", sec)
        self.assertEqual(res["again"]["awt_record"], sec, "stable text, so the prompt cache holds")

    def test_p4_pi_restores_it_for_a_resumed_session_that_was_compacted(self):
        res = self.drive(self.pi_js([{"type": "message"}, {"type": "compaction"}]))
        self.assertIn("token-zq41", res["resumed"]["awt_record"])

    def test_p5_pi_silent_without_awt_dir(self):
        res = self.drive(self.pi_js([{"type": "compaction"}]), awt_dir=False)
        self.assertEqual(res["after"], {})
        self.assertEqual(res["resumed"], {})


if __name__ == "__main__":
    unittest.main()
