"""Node tree, reading across nodes (SPEC.md, "Reading across nodes"). End to end, real awt."""
import json, os, re, shutil, unittest

import test_awt
import test_tree


class Reads(test_tree.TreeBase):
    def decide(self, node, text, *extra):
        self.ok("decide", text, "--why", "because", *extra, root=node)

    def test_lineage_and_inherited_rules(self):  # T20
        root, ws, task, agent, sub = self.chain()
        self.decide(ws, "never force push", "--tag", "rule")
        self.decide(ws, "prefer small prs")
        self.decide(root, "use utc everywhere", "--tag", "rule")
        self.decide(task, "task local rule", "--tag", "rule")
        out = self.ok("resume", root=agent).stdout
        self.assertIn("## Lineage", out)
        lines = out.splitlines()
        order = [next(i for i, l in enumerate(lines) if l.startswith(k)) for k in ("root ", "workspace Alpha", "task Fix login")]
        self.assertEqual(order, sorted(order), out)
        self.assertIn("never force push", out)
        self.assertIn("use utc everywhere", out)
        self.assertIn("task local rule", out)
        self.assertNotIn("prefer small prs", out)
        self.assertRegex(out, r"never force push.*|.*\[rule[, ]+workspace")
        self.assertLess(out.index("use utc everywhere"), out.index("never force push"))

    def test_children_rollup(self):  # T21
        root, ws, task, agent, sub = self.chain()
        a2 = self.mk("agent", "chat-2", task)
        a3 = self.mk("agent", "chat-3", task)
        self.ok("state", "--now", "wiring the retry loop", "--next", "tests", root=a2)
        self.ok("status", "done", root=a3)
        out = self.ok("resume", root=task).stdout
        self.assertIn("## Children", out)
        sect = out.split("## Children")[1].split("\n## ")[0]
        self.assertIn("wiring the retry loop", sect)
        self.assertRegex(sect, r"chat-1.*no state")
        self.assertLess(sect.index("chat-2"), sect.index("chat-3"))  # active before done
        self.assertNotIn("## Children", self.ok("resume", root=sub).stdout)

    def test_budget_at_max_fill(self):  # T22
        root, ws, task, agent, sub = self.chain()
        for i in range(12):
            self.decide(ws, ("rule-%02d " % i) + "r" * 280, "--tag", "rule")
        parent = task
        for i in range(5):
            parent = self.mk("task", "t%d" % i, parent, "--goal", "g" * 240, "--done", "d")
        for i in range(40):
            a = self.mk("agent", "m%02d" % i, parent)
            self.ok("state", "--now", "n" * 690, "--next", "x" * 290, root=a)
        for i in range(25):
            self.mk("agent", "c%02d" % i, parent)
        leaf = parent
        out = self.ok("resume", root=leaf).stdout
        self.assertLessEqual(len(out), 5200, len(out))
        self.assertRegex(out, r"\+\d+ more: .*list nodes")
        for l in out.splitlines():
            self.assertLessEqual(len(l), 900, l[:80])

    def test_standalone_brief_has_no_tree_sections(self):  # T23
        self.init()
        out = self.ok("resume").stdout
        self.assertNotIn("## Lineage", out)
        self.assertNotIn("## Children", out)
        self.assertLessEqual(len(out), 4400)

    def test_list_nodes_tree_json(self):  # T24
        root, ws, task, agent, sub = self.chain()
        self.mk("agent", "chat-2", task)
        self.ok("state", "--now", "doing x", "--next", "y", root=agent)
        self.ok("ask", "who owns this?", root=sub)
        rows = json.loads(self.ok("list", "nodes", "--json", root=root).stdout)
        walked = []
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d != ".awt"]
            if os.path.isdir(os.path.join(dp, ".awt")) and dp != root:
                walked.append(os.path.relpath(dp, root))
        self.assertEqual(sorted(r["path"] for r in rows), sorted(walked))
        self.assertEqual(set(rows[0]), {"path", "kind", "name", "key", "status", "goal", "now", "state_ts", "open_questions", "attention_effects", "depth"})
        by = {r["name"]: r for r in rows}
        self.assertEqual(by["chat-1"]["now"], "doing x")
        self.assertEqual(by["sub-1"]["open_questions"], 1)
        self.assertEqual(by["Alpha"]["depth"], 1)
        self.assertEqual(by["sub-1"]["depth"], 4)
        text = self.ok("list", "tree", root=root).stdout
        for n in ("Alpha", "Fix login", "chat-1", "chat-2", "sub-1"):
            self.assertIn(n, text)
        self.assertLess(text.index("Alpha"), text.index("Fix login"))
        self.assertRegex(next(l for l in text.splitlines() if "sub-1" in l), r"\?")  # open question marker
        self.ok("status", "done", root=self.mk("agent", "gone", task))
        names = lambda r: {x["name"] for x in json.loads(self.ok("list", "nodes", "--json", *r, root=root).stdout)}
        self.assertNotIn("gone", names([]))
        self.assertIn("gone", names(["--all"]))

    def test_json_sections(self):
        self.init()
        self.ok("note", "a note")
        self.ok("decide", "x", "--why", "y", "--tag", "rule")
        notes = json.loads(self.ok("list", "notes", "--json").stdout)
        self.assertEqual([n["text"] for n in notes], ["a note"])
        decs = json.loads(self.ok("list", "decisions", "--json").stdout)
        self.assertEqual(decs[0]["tags"], ["rule"])
        r = json.loads(self.ok("resume", "--json").stdout)
        self.assertEqual({"node", "status", "goal", "done_means", "state", "open_questions", "attention_effects", "decisions", "lineage", "children", "brief"}, set(r))
        self.assertIn("# awt task", r["brief"])

    def test_find_across_nodes(self):  # T25
        root, ws, task, agent, sub = self.chain()
        for node, rel in ((sub, "docs/deep.md"), (root, "docs/top.md")):
            p = os.path.join(node, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as g:
                g.write("zebra crossing\n")
        self.ok("note", "zebra in an event", root=sub)
        self.assertEqual(self.ok("find", "zebra", root=task).stdout.strip(), "")
        down = self.ok("find", "--down", "zebra", root=task).stdout
        self.assertIn("deep.md", down)
        self.assertIn("zebra in an event", down)
        self.assertNotIn("top.md", down)
        up = self.ok("find", "--up", "zebra", root=task).stdout
        self.assertIn("top.md", up)
        self.assertNotIn("deep.md", up)
        both = self.ok("find", "--tree", "zebra", root=task).stdout
        self.assertIn("deep.md", both)
        self.assertIn("top.md", both)
        self.assertIn("../../../../docs/top.md", both)
        many = self.mk("agent", "many", task)
        with open(os.path.join(many, "docs.txt"), "w") as g:
            g.write("".join("zebra %d\n" % i for i in range(100)))
        capped = self.ok("find", "--down", "zebra", root=task).stdout.splitlines()
        self.assertEqual(len(capped), 41)
        self.assertRegex(capped[-1], r"^\+\d+ more")

    def test_ref_kinds(self):  # T26
        root, ws, task, agent, sub = self.chain()
        other = self.mk("task", "other", ws, "--goal", "g", "--done", "d")
        self.ok("ref", other, "--title", "sibling", root=task)
        self.ok("ref", "paseo:agent/agt_1", "--title", "chat", root=task)
        refs = {r["target"]: r for r in self.rows_of(task, "ref")}
        r = refs[other]
        self.assertEqual((r["kind"], r["access"], r["path"]), ("node", "ok", "../other"))
        self.assertEqual(refs["paseo:agent/agt_1"]["kind"], "paseo")
        self.assertIn("../other", self.ok("list", "refs", root=task).stdout)

    def test_moving_a_subtree_keeps_it_valid(self):  # T13
        root, ws, task, agent, sub = self.chain()
        dest = os.path.join(self.tmp, "tree2")
        os.makedirs(dest)
        self.ok("init", "--kind", "root", root=dest)
        moved = os.path.join(dest, "workspaces", "alpha")
        shutil.move(ws, moved)
        out = self.ok("resume", root=os.path.join(moved, "tasks", "fix-login", "agents", "chat-1")).stdout
        self.assertIn("workspace Alpha", out)
        self.assertRegex(out.split("## Lineage")[1].split("\n## ")[0], r"root tree2")
        rows = json.loads(self.ok("list", "nodes", "--json", root=dest).stdout)
        self.assertEqual(len(rows), 4)


class Status(test_tree.TreeBase):
    def test_done_blocked_by_descendants(self):  # T30
        root, ws, task, agent, sub = self.chain()
        child = self.mk("task", "child", task, "--goal", "g", "--done", "d")
        r = self.refuses("status", "done", root=task)
        self.assertIn("child", r.stderr)
        self.ok("status", "done", root=child)
        self.ok("ask", "who?", root=sub)
        r = self.refuses("status", "done", root=task)
        self.assertIn("sub-1", r.stderr)
        qid = self.rows_of(sub, "question")[0]["id"]
        self.ok("answer", qid, "me", root=sub)
        self.ok("effect", "plan", "--target", "slack:#x", "--run", "true", root=agent)
        r = self.refuses("status", "done", root=task)
        self.assertIn("chat-1", r.stderr)
        eid = self.rows_of(agent, "effect")[0]["id"]
        self.ok("effect", "mark", eid, "dropped", root=agent)
        self.ok("status", "done", root=task)

    def test_paused_always_allowed(self):  # T31
        root, ws, task, agent, sub = self.chain()
        self.ok("ask", "who?", root=sub)
        self.ok("status", "paused", root=ws)

    def test_agent_done_never_blocks_parent(self):  # T32
        root, ws, task, agent, sub = self.chain()
        self.ok("status", "done", root=sub)
        self.ok("status", "done", root=agent)
        self.ok("status", "done", root=task)


class Doctor(test_tree.TreeBase):
    def test_clean_tree_has_no_warnings(self):
        root, ws, task, agent, sub = self.chain()
        for node in (root, ws, task, agent, sub):
            r = self.awt("doctor", root=node, env=dict(self.env, PATH=os.path.dirname(test_awt.AWT) + os.pathsep + self.env["PATH"], AWT_DIR=node))
            self.assertNotIn("fail ", r.stdout, (node, r.stdout))
            self.assertNotIn("warn ", r.stdout.replace("warn path is a sync", ""), (node, r.stdout))

    def test_defects_are_reported(self):  # T40
        root, ws, task, agent, sub = self.chain()
        os.makedirs(os.path.join(task, "agents", ".new-abc123", ".awt"))
        d1 = self.mk("agent", "dup1", task, "--key", "K")
        d2 = self.mk("agent", "dup2", task, "--key", "K2")
        with open(os.path.join(d2, ".awt", "events.jsonl")) as g:
            txt = g.read()
        with open(os.path.join(d2, ".awt", "events.jsonl"), "w") as g:
            g.write(txt.replace('"K2"', '"K"'))
        shutil.move(sub, os.path.join(task, "tasks_wrong"))  # a node outside a reserved dir is not a child
        os.symlink(root, os.path.join(task, "agents", "loop"))
        wrong = os.path.join(ws, "tasks", "fix-login", "agents", "chat-1")
        os.makedirs(os.path.join(ws, "workspaces"), exist_ok=True)
        shutil.copytree(wrong, os.path.join(ws, "workspaces", "misplaced"))
        r = self.awt("doctor", root=ws)
        out = r.stdout
        for needle in (".new-abc123", "duplicate key", "symlink", "misplaced"):
            self.assertIn(needle, out, out)
        self.assertNotIn("Traceback", r.stderr)

    def test_awt_dir_without_awt_on_path(self):
        root, ws, task, agent, sub = self.chain()
        env = dict(self.env, PATH="/usr/bin:/bin", AWT_DIR=agent)
        r = self.awt("doctor", root="", env=env, cwd=self.tmp)
        self.assertRegex(r.stdout, r"warn .*PATH")


if __name__ == "__main__":
    unittest.main()
