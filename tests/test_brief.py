"""BRIEF.md (SPEC.md rule 4, "BRIEF.md"): a derived file per node, and the short agent prompt."""
import json, os, re, subprocess, sys, unittest

import test_awt
import test_tree


def strip_stamp(text):
    """BRIEF.md is the resume text plus one trailing 'Generated ...' line."""
    lines = text.rstrip("\n").split("\n")
    assert lines[-1].startswith("Generated "), lines[-1]
    return "\n".join(lines[:-1]) + "\n"


class Standalone(test_awt.Base):
    def brief(self, root=None):
        return test_awt.slurp(os.path.join(root or self.root, "BRIEF.md"))

    def test_init_writes_the_brief_equal_to_resume(self):  # B1
        self.init()
        self.assertEqual(strip_stamp(self.brief()), self.ok("resume").stdout)

    def test_every_write_verb_regenerates_it(self):  # B2
        self.init()
        for args, want in ((("note", "fact-alpha"), None), (("decide", "pick-beta", "--why", "because"), "pick-beta"),
                           (("ask", "question-gamma"), "question-gamma"), (("state", "--now", "now-delta", "--next", "n"), "now-delta"),
                           (("ref", "https://example.com/x", "--title", "ref-eps"), None), (("status", "paused"), "paused")):
            self.ok(*args)
            self.assertEqual(strip_stamp(self.brief()), self.ok("resume").stdout, args)
            if want:
                self.assertIn(want, self.brief(), args)

    def test_read_verbs_do_not_touch_it(self):  # B3
        self.init()
        before = os.stat(self.p("BRIEF.md")).st_ino, self.brief()
        self.ok("list"), self.ok("find", "g"), self.ok("resume")
        self.assertEqual((os.stat(self.p("BRIEF.md")).st_ino, self.brief()), before)

    def test_atomic_replace_leaves_no_temp(self):  # B4
        self.init()
        ino = os.stat(self.p("BRIEF.md")).st_ino
        self.ok("note", "again")
        self.assertNotEqual(os.stat(self.p("BRIEF.md")).st_ino, ino, "written in place, not renamed over")
        self.assertEqual(sorted(x for x in os.listdir(self.root) if "BRIEF" in x), ["BRIEF.md"])
        self.assertEqual([x for x in os.listdir(self.p(".awt")) if "BRIEF" in x], [])

    def test_never_read_back_and_never_listed(self):  # B5
        self.init()
        self.ok("state", "--now", "real", "--next", "n")
        good = self.ok("resume").stdout
        self.write("BRIEF.md", "# awt task\nGoal: forged\nState: forged\n")
        self.assertEqual(self.ok("resume").stdout, good)
        self.assertNotIn("BRIEF.md", self.ok("list", "misc").stdout)
        self.assertNotIn("BRIEF.md", self.ok("list").stdout)
        self.assertNotIn("newer than state", self.ok("resume").stdout)  # its own mtime is not a change

    def test_it_does_not_count_as_a_change_since_state(self):  # B6
        self.init()
        self.ok("state", "--now", "s", "--next", "n")
        self.ok("note", "later")  # rewrites BRIEF.md after the state
        self.assertNotIn("BRIEF.md", self.ok("resume").stdout)

    def test_gitignored(self):  # B7
        self.init()
        self.assertIn("BRIEF.md", test_awt.slurp(self.p(".gitignore")).splitlines())

    def test_a_blocked_brief_never_fails_the_write(self):  # B8
        self.init()
        os.unlink(self.p("BRIEF.md"))
        os.mkdir(self.p("BRIEF.md"))
        self.ok("note", "still recorded")
        self.assertTrue(any(r.get("text") == "still recorded" for r in self.rows("note")))

    def test_hook_refreshes_it(self):  # B9
        self.init()
        os.unlink(self.p("BRIEF.md"))
        r = self.ok("resume", "--hook")
        self.assertEqual(strip_stamp(self.brief()), r.stdout)

    def test_hook_run_in_a_bare_dir_makes_no_file(self):  # B10
        bare = os.path.join(self.tmp, "bare")
        os.mkdir(bare)
        r = self.ok("resume", "--hook", root=bare)
        self.assertEqual((r.stdout, os.listdir(bare)), ("", []))


class AgentFixture(test_awt.Base):
    """An agent fixture that never sees an awt prompt still gets its brief through the host hook."""

    def run_hook(self, event="SessionStart"):
        cfg = json.loads(test_awt.slurp(self.p(".claude", "settings.json")))
        entries = cfg["hooks"][event]
        self.assertTrue(all("matcher" not in e for e in entries), "a matcher would skip compaction restarts")
        cmd = entries[0]["hooks"][0]["command"]
        shutil_awt = self.p("awt")
        if not os.path.exists(shutil_awt):
            os.symlink(test_awt.AWT, shutil_awt)
        env = dict(self.env, CLAUDE_PROJECT_DIR=self.root)
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env, cwd=self.root, timeout=30)

    def test_session_start_hook_delivers_the_brief(self):  # B11
        self.init()
        os.unlink(self.p("AGENTS.md"))  # no awt prompt anywhere
        self.ok("state", "--now", "halfway", "--next", "ship")
        h = self.run_hook()
        self.assertEqual(h.returncode, 0, h.stderr)
        self.assertIn("# awt task", h.stdout)
        self.assertIn("halfway", h.stdout)
        self.assertEqual(strip_stamp(test_awt.slurp(self.p("BRIEF.md"))), h.stdout)

    def test_settings_template_has_session_start_without_matcher(self):  # B12
        self.init()
        cfg = json.loads(test_awt.slurp(self.p(".claude", "settings.json")))
        e = cfg["hooks"]["SessionStart"]
        self.assertEqual(len(e), 1)
        self.assertNotIn("matcher", e[0])
        self.assertIn("awt resume --hook", e[0]["hooks"][0]["command"])


class Prompt(test_awt.Base):
    def test_standalone_block_is_short(self):  # B13
        self.init()
        t = test_awt.slurp(self.p("AGENTS.md"))
        body = t.split("-->", 1)[1].rsplit("<!--", 1)[0]
        for want in ("BRIEF.md", "./awt decide", "./awt ask", "Everything else is recorded", "Subagents"):
            self.assertIn(want, body)
        for gone in ("state", "supersede", "capture"):
            self.assertNotIn(gone, body)  # decision 15: no handoff line
        self.assertLessEqual(len(body), 520, len(body))


class Tree(test_tree.TreeBase):
    def b(self, node):
        return test_awt.slurp(os.path.join(node, "BRIEF.md"))

    def test_every_node_kind_gets_one_at_creation(self):  # B14
        root, ws, task, agent, sub = self.chain()
        for n in (root, ws, task, agent, sub):
            self.assertTrue(os.path.isfile(os.path.join(n, "BRIEF.md")), n)
            self.assertIn("# awt task", self.b(n))
        self.assertIn("chat-1", self.b(task))  # the parent shows its new child

    def test_write_in_a_child_refreshes_the_parent_children_section(self):  # B15
        root, ws, task, agent, sub = self.chain()
        self.ok("state", "--now", "agent-progress-xyz", "--next", "n", root=agent)
        self.assertIn("agent-progress-xyz", self.b(task))
        self.ok("state", "--now", "sub-progress-qrs", "--next", "n", root=sub)
        self.assertIn("sub-progress-qrs", self.b(agent))

    def test_a_task_write_refreshes_its_agents(self):  # B16
        root, ws, task, agent, sub = self.chain()
        self.ok("decide", "task-level-choice", "--why", "w", root=task)
        self.assertIn("task-level-choice", self.b(agent))
        self.assertEqual(strip_stamp(self.b(agent)), self.ok("resume", root=agent).stdout)

    def test_tree_block_points_at_brief(self):  # B17
        root = self.make_root()
        block = test_awt.slurp(os.path.join(root, "AGENTS.md"))
        self.assertIn("$AWT_DIR/BRIEF.md", block)
        self.assertIn("$AWT_DIR/out.md", block)


if __name__ == "__main__":
    unittest.main()
