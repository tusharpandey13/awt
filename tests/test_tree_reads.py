"""Node tree, reading across nodes (SPEC.md, "Reading across nodes"). End to end, real awt."""
import json, os, re, shutil, socket, subprocess, unittest

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
        self.assertRegex(out, r"\[rule, workspace Alpha\] never force push")
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
        self.assertEqual(set(rows[0]), {"path", "kind", "name", "key", "status", "goal", "now", "state_ts", "out_ts", "out_bytes", "open_questions", "attention_effects", "depth"})
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
        self.assertEqual([r["name"] for r in json.loads(self.ok("list", "tree", "--json", root=root).stdout)], [r["name"] for r in rows])
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
        self.assertEqual({"node", "status", "goal", "done_means", "state", "open_questions", "attention_effects", "decisions", "lineage", "children", "task", "brief"}, set(r))
        self.assertIsNone(r["task"])
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

    def test_find_tree_covers_whole_tree(self):  # T25b
        root, ws, task, agent, sub = self.chain()
        freeze = self.mk("task", "freeze", ws, "--goal", "g", "--done", "d")
        fa = self.mk("agent", "fa", freeze)
        self.ok("decide", "parsekit freezes the lexer API", "--why", "stability", root=freeze)
        self.ok("note", "parsekit token cache is per-thread", root=fa)
        out = self.ok("find", "--tree", "parsekit", root=agent).stdout
        self.assertIn("../../freeze", out)
        self.assertIn("parsekit freezes the lexer API", out)
        self.assertIn("../../freeze/agents/fa", out)
        self.assertEqual(self.ok("find", "--down", "parsekit", root=agent).stdout.strip(), "")
        self.assertEqual(self.ok("find", "--up", "parsekit", root=agent).stdout.strip(), "")
        for i in range(30):
            self.ok("note", "parsekit sibling note %d" % i, root=freeze)
            self.ok("note", "parsekit own note %d" % i, root=task)
        capped = self.ok("find", "--tree", "parsekit", root=agent).stdout.splitlines()
        self.assertEqual(len(capped), 41)
        self.assertRegex(capped[-1], r"^\+\d+ more")

    def test_find_tree_standalone_falls_back(self):  # T25c
        node = os.path.join(self.top, "solo")
        os.makedirs(node)
        self.ok("init", root=node)
        self.ok("note", "parsekit standalone fact", root=node)
        self.assertIn("parsekit standalone fact", self.ok("find", "--tree", "parsekit", root=node).stdout)

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
        for needle in (".new-abc123", "duplicate key", "symlink", "misplaced", "tasks_wrong"):
            self.assertIn(needle, out, out)
        self.assertNotIn("Traceback", r.stderr)

    def test_awt_dir_without_awt_on_path(self):
        root, ws, task, agent, sub = self.chain()
        env = dict(self.env, PATH="/usr/bin:/bin", AWT_DIR=agent)
        r = self.awt("doctor", root="", env=env, cwd=self.tmp)
        self.assertRegex(r.stdout, r"warn .*PATH")


def tgit(path, *args):
    return subprocess.run(["git", "-C", path] + list(args), capture_output=True, text=True, env=dict(os.environ, **test_awt.GITENV), check=True)


class Review(test_tree.TreeBase):
    """PR review fixes: limits, ancestors, JSON key sets, budgets, ordering."""

    def nest(self, ws, n):
        p, nodes = ws, []
        for i in range(n):
            p = self.mk("task", "t%d" % i, p, "--goal", "g", "--done", "d")
            nodes.append(p)
        return nodes

    def test_limits_are_reported(self):
        root = self.make_root()
        ws = self.mk("workspace", "Alpha", root)
        nodes = self.nest(ws, 10)
        for p in nodes[:8]:
            self.ok("status", "paused", root=p)  # t8 and t9 sit beyond depth 8 and stay active
        r = self.refuses("status", "done", root=ws)
        self.assertRegex(r.stderr, r"exceeds depth 8")
        self.assertRegex(self.ok("doctor", root=ws).stdout, r"warn .*exceeds depth 8")
        self.assertRegex(self.ok("find", "--down", "g", root=ws).stdout, r"exceeds depth 8")

    def test_ancestors_stop_at_first_root_and_follow_reserved_dirs(self):
        self.init()
        self.ok("note", "outer")
        self.ok("decide", "outer private rule", "--why", "x", "--tag", "rule")
        tree = os.path.join(self.root, "misc", "tree")
        os.makedirs(tree)
        self.ok("init", "--kind", "root", root=tree)
        ws = self.mk("workspace", "Alpha", tree)
        out = self.ok("resume", root=ws).stdout
        self.assertIn("root tree", out)
        self.assertNotIn("outer private rule", out)
        self.assertNotIn("g [", out.split("## Lineage")[1].split("\n## ")[0].replace("root tree", ""))
        # a node in a plain subdirectory of a node has no parent
        root, ws2, task, agent, sub = self.chain()
        stray = os.path.join(task, "foo", "stray")
        shutil.copytree(agent, stray)
        self.assertNotIn("## Lineage", self.ok("resume", root=stray).stdout)

    def test_json_key_sets_are_stable(self):
        root, ws, task, agent, sub = self.chain()
        n = agent
        self.ok("decide", "plain", "--why", "w", root=n)
        self.ok("decide", "tagged", "--why", "w", "--tag", "rule", root=n)
        first = self.rows_of(n, "decision")[0]["id"]
        self.ok("decide", "newer", "--why", "w", "--supersedes", first, root=n)
        self.ok("ask", "q1", root=n)
        self.ok("ask", "q2", root=n)
        self.ok("answer", self.rows_of(n, "question")[0]["id"], "a", root=n)
        self.ok("note", "n1", root=n)
        self.ok("note", "n2", root=n)
        self.ok("state", "--now", "x", "--next", "y", root=n)
        self.ok("state", "--now", "x2", "--next", "y2", "--scope", "side", root=n)
        self.ok("effect", "plan", "--target", "slack:#a", "--run", "true", root=n)
        self.ok("effect", "plan", "--target", "slack:#b", "--run", "true", "--why", "w", root=n)
        self.ok("ref", "https://example.test/a", "--title", "t", root=n)
        self.ok("ref", "https://example.test/b", "--title", "t", "--why", "w", root=n)
        keys = {}
        for sect in ("decisions", "questions", "effects", "notes", "state", "refs"):
            rows = json.loads(self.ok("list", sect, "--json", "--all", root=n).stdout)
            self.assertGreaterEqual(len(rows), 2, sect)
            self.assertEqual(len({tuple(sorted(r)) for r in rows}), 1, (sect, [sorted(r) for r in rows]))
            keys[sect] = set(rows[0])
        self.assertEqual(keys["decisions"], {"ts", "by", "id", "choice", "why", "tags", "supersedes", "superseded_by"})
        self.assertEqual(keys["questions"], {"ts", "by", "id", "text", "answer"})
        self.assertEqual(keys["notes"], {"ts", "by", "id", "text"})
        self.assertEqual(keys["state"], {"ts", "by", "scope", "now", "next"})
        self.assertEqual(keys["refs"], {"ts", "by", "target", "title", "kind", "why", "access", "path", "branch", "key"})
        self.assertEqual(keys["effects"], {"ts", "by", "id", "target", "why", "body", "run", "state", "attempt"})
        for sect in ("context", "docs", "outbox", "misc"):
            for r in json.loads(self.ok("list", sect, "--json", root=n).stdout):
                self.assertEqual(set(r), {"path", "title"})
        r = json.loads(self.ok("resume", "--json", "--scope", "side", root=n).stdout)
        self.assertEqual(r["state"]["scope"], "side")
        self.assertEqual(set(r["task"]), {"path", "depth", "kind", "name", "key", "status", "goal", "now", "state_ts", "out_ts", "out_bytes",
                                          "open_questions", "attention_effects", "done_means", "state", "decisions"})
        self.assertEqual(r["task"]["name"], "Fix login")

    def test_local_decisions_survive_inherited_rules(self):
        root = self.make_root()
        ws = self.mk("workspace", "Alpha", root)
        self.ok("decide", "ws rule " + "w" * 110, "--why", "x", "--tag", "rule", root=ws)
        p = ws
        for i in range(7):
            p = self.mk("task", "lvl%d" % i, p, "--goal", "g", "--done", "d")
            self.ok("decide", ("lvl%d rule " % i) + "r" * 110, "--why", "x", "--tag", "rule", root=p)
        self.ok("decide", "local choice stays", "--why", "x", root=p)
        out = self.ok("resume", root=p).stdout
        dec = out.split("## Decisions")[1].split("\n## ")[0]
        self.assertIn("local choice stays", dec)
        self.assertRegex(dec, r"\[rule, task lvl1\] lvl1 rule")
        self.assertRegex(dec, r"\+\d+ more: awt list decisions.*awt find --up rule")
        self.assertLessEqual(len(dec), 820)

    def test_doctor_tolerates_unreadable_dir(self):
        root, ws, task, agent, sub = self.chain()
        d = os.path.join(ws, "tasks")
        os.chmod(d, 0)
        self.addCleanup(os.chmod, d, 0o755)
        r = self.awt("doctor", root=root)
        self.assertNotIn("error:", r.stderr)
        self.assertRegex(r.stdout, r"warn .*unreadable")
        self.assertIn("python", r.stdout)

    def test_status_done_refusal_is_capped(self):
        root, ws, task, agent, sub = self.chain()
        for i in range(25):
            self.mk("agent", "a%02d" % i, task)
            self.ok("ask", "who %d" % i, root=os.path.join(task, "agents", "a%02d" % i))
        r = self.refuses("status", "done", root=task)
        self.assertRegex(r.stderr, r"\+\d+ more")
        self.assertLess(len(r.stderr), 3000)

    def test_children_order_active_paused_done(self):
        root, ws, task, agent, sub = self.chain()
        for name, st in (("c-active", None), ("c-paused", "paused"), ("c-done", "done")):
            a = self.mk("agent", name, task)
            self.ok("state", "--now", "w " + name, "--next", "n", root=a)
            if st:
                self.ok("status", st, root=a)
        sect = self.ok("resume", root=task).stdout.split("## Children")[1].split("\n## ")[0]
        self.assertLess(sect.index("c-active"), sect.index("c-paused"))
        self.assertLess(sect.index("c-paused"), sect.index("c-done"))

    def test_one_definition_of_attention(self):
        root, ws, task, agent, sub = self.chain()
        for step, extra in (("planned", {"target": "slack:#x", "key": "k", "run": "true"}), ("claimed", {"pid": os.getpid(), "timeout": 300})):
            row = dict(v=1, ts=test_awt.ts(), type="effect", host=socket.gethostname(), by="t", id="e-00000001", step=step, attempt=1)
            row.update(extra)
            with open(os.path.join(agent, ".awt", "events.jsonl"), "a") as g:
                g.write(json.dumps(row) + "\n")
        parent = self.ok("resume", root=task).stdout
        self.assertRegex(parent, r"chat-1 \[active\] \(1 open\)")
        child = self.ok("resume", root=agent).stdout
        self.assertIn("## Effects needing attention", child)
        self.assertIn("e-00000001", child)
        self.assertEqual([r["attention_effects"] for r in json.loads(self.ok("list", "nodes", "--json", root=task).stdout) if r["name"] == "chat-1"], [1])


class ReadLayer(test_tree.TreeBase):
    """Read-layer items of SPEC 'Reading across nodes' that PR 3 deferred."""

    def test_task_section_for_agent_nodes(self):
        root, ws, task, agent, sub = self.chain()
        self.ok("state", "--now", "task wide progress", "--next", "task next", root=task)
        self.ok("ask", "task level question?", root=task)
        self.ok("decide", "task plain decision", "--why", "w", root=task)
        self.ok("decide", "task rule decision", "--why", "w", "--tag", "rule", root=task)
        self.ok("effect", "plan", "--target", "slack:#t", "--run", "true", root=task)
        out = self.ok("resume", root=agent).stdout
        self.assertIn("## Task", out)
        sect = out.split("## Task")[1].split("\n## ")[0]
        for needle in ("fix it", "merged", "task wide progress", "task next", "task level question?", "slack:#t", "task plain decision"):
            self.assertIn(needle, sect)
        self.assertNotIn("task rule decision", sect)
        self.assertIn("task rule decision", out.split("## Decisions")[1])
        self.assertLessEqual(len(sect) + 8, 1800)
        self.assertLess(out.index("## Lineage"), out.index("## Task"))
        self.assertNotIn("## Task", self.ok("resume", root=task).stdout)
        self.assertNotIn("## Task", self.ok("resume", root=ws).stdout)
        j = json.loads(self.ok("resume", "--json", root=agent).stdout)
        self.assertEqual(j["task"]["done_means"], "merged")
        self.assertEqual(j["task"]["state"]["now"], "task wide progress")
        self.assertEqual(len(j["task"]["open_questions"]), 1)
        self.assertEqual([d["choice"] for d in j["task"]["decisions"]], ["task plain decision"])

    def test_task_section_budget_and_total(self):
        root, ws, task, agent, sub = self.chain()
        self.ok("state", "--now", "n" * 690, "--next", "x" * 290, root=task)
        for i in range(6):
            self.ok("state", "--now", "n" * 690, "--next", "x", "--scope", "s%d" % i, root=task)
            self.ok("ask", "q" * 390, root=task)
            self.ok("decide", "c" * 290, "--why", "w", root=task)
            self.ok("effect", "plan", "--target", "slack:#t%d" % i, "--run", "true", root=task)
        for i in range(12):
            self.ok("decide", "ws rule %d " % i + "r" * 280, "--why", "w", "--tag", "rule", root=ws)
        self.ok("state", "--now", "n" * 690, "--next", "x" * 290, root=agent)
        out = self.ok("resume", root=agent).stdout
        sect = out.split("## Task")[1].split("\n## ")[0]
        self.assertLessEqual(len(sect) + 8, 1800)
        self.assertRegex(sect, r"\+\d+ more: awt list \w+ --dir ")
        self.assertLessEqual(len(out), 7000)

    def test_children_without_state_show_out_md(self):
        root, ws, task, agent, sub = self.chain()
        with open(os.path.join(sub, "out.md"), "w") as g:
            g.write("x" * 2048)
        sect = self.ok("resume", root=agent).stdout.split("## Children")[1].split("\n## ")[0]
        self.assertRegex(sect, r"sub-1.*out\.md (just now|\d+\w+ ago), 2\.0K")
        self.assertRegex(self.ok("resume", root=task).stdout.split("## Children")[1], r"chat-1.*no state")

    def test_ancestor_repo_refs_in_changes(self):
        root, ws, task, agent, sub = self.chain()
        repo = os.path.join(self.tmp, "parsekit")
        os.makedirs(repo)
        tgit(repo, "init", "-q")
        tgit(repo, "commit", "-q", "--allow-empty", "-m", "base")
        self.ok("ref", repo, "--title", "repo", root=ws)
        self.ok("state", "--now", "a", "--next", "b", root=agent)
        tgit(repo, "commit", "-q", "--allow-empty", "-m", "after state")
        chg = self.ok("resume", root=agent).stdout.split("## Changes since newest state")[1].split("\n## ")[0]
        self.assertRegex(chg, r"repo parsekit: \d new commits \(after state")

    def test_brief_commands_and_repo_section_per_node_kind(self):  # T28
        root, ws, task, agent, sub = self.chain()
        repo = os.path.join(self.tmp, "parsekit")
        os.makedirs(repo)
        tgit(repo, "init", "-q")
        tgit(repo, "commit", "-q", "--allow-empty", "-m", "base")
        self.ok("ref", repo, "--title", "repo", root=ws)  # the repo is the workspace's, not the task's
        self.ok("state", "--now", "a", "--next", "b", root=task)
        tgit(repo, "commit", "-q", "--allow-empty", "-m", "after task state")
        env = dict(self.env, PATH=os.path.dirname(test_awt.AWT) + os.pathsep + self.env["PATH"])
        for n in (root, ws, task, agent, sub):
            out = self.ok("resume", root=n, env=env).stdout
            self.assertNotIn("./awt", out, n)
            self.assertRegex(out, r"(?<![./\w])awt (list|state|find)", n)
        chg = self.ok("resume", root=task).stdout.split("## Changes since newest state")[1].split("\n## ")[0]
        self.assertRegex(chg, r"repo parsekit: \d new commits? \(after task state")
        # A standalone task: ./awt everywhere, and its own repo ref feeds the same section.
        d = os.path.join(self.tmp, "solo")
        os.mkdir(d)
        self.ok("init", "--goal", "g", "--done", "d", root=d)
        self.ok("ref", repo, "--title", "repo", root=d)
        self.ok("state", "--now", "a", "--next", "b", root=d)
        tgit(repo, "commit", "-q", "--allow-empty", "-m", "after solo state")
        out = self.ok("resume", root=d, env=env).stdout
        self.assertRegex(out, r"\./awt (list|state|find)")
        self.assertNotRegex(out, r"(?<![./\w])awt (list|state|find)")
        self.assertRegex(out.split("## Changes since newest state")[1].split("\n## ")[0], r"repo parsekit: \d new commits? \(after solo state")

    def test_printed_commands_use_awt_in_tree_nodes(self):
        root, ws, task, agent, sub = self.chain()
        for n in (root, ws, task, agent):
            out = self.ok("resume", root=n).stdout
            self.assertNotIn("./awt", out, n)
            self.assertIn("awt ", out)
        self.init()
        self.assertIn("./awt", self.ok("resume").stdout)

    def test_ref_resolves_by_key_then_path(self):
        root, ws, task, agent, sub = self.chain()
        ws2 = self.mk("workspace", "Beta", root)
        other = self.mk("task", "other", ws, "--goal", "g", "--done", "d", "--key", "k:other")
        plain = self.mk("task", "plain", ws, "--goal", "g", "--done", "d")
        self.ok("ref", other, "--title", "keyed", root=task)
        self.ok("ref", plain, "--title", "unkeyed", root=task)
        self.assertEqual({r["target"]: r.get("key") for r in self.rows_of(task, "ref")}, {other: "k:other", plain: None})
        refs = lambda: {r["title"]: r for r in json.loads(self.ok("list", "refs", "--json", root=task).stdout)}
        self.assertEqual({r["access"] for r in refs().values()}, {"ok"})
        moved = os.path.join(ws2, "tasks", "other")
        shutil.move(other, moved)
        shutil.move(plain, os.path.join(ws2, "tasks", "plain"))
        r = refs()
        self.assertEqual((r["keyed"]["access"], os.path.normpath(os.path.join(task, r["keyed"]["path"]))), ("ok", moved))
        self.assertEqual(r["unkeyed"]["access"], "none")
        self.assertRegex(self.ok("list", "refs", root=task).stdout, r"node, none.*unkeyed|\[none.*unkeyed")
        self.assertEqual(self.rows_of(task, "ref")[0]["access"], "ok")  # stored rows are unchanged


class ReadLayerAccess(test_tree.TreeBase):
    def test_ref_to_nothing_is_access_none(self):
        root, ws, task, agent, sub = self.chain()
        other = self.mk("task", "other", ws, "--goal", "g", "--done", "d")
        self.ok("ref", other, "--title", "gone soon", root=task)
        shutil.rmtree(other)
        self.assertIn("none", self.ok("list", "refs", root=task).stdout)
        self.assertIn("1 no-access", self.ok("resume", root=task).stdout)


if __name__ == "__main__":
    unittest.main()
