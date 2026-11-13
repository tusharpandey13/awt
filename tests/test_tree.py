"""Node tree (SPEC.md, "Node tree"). End to end: every check runs the real awt in a temp HOME."""
import concurrent.futures as cf, hashlib, json, os, re, shutil, subprocess, sys, unittest

import test_awt


class TreeBase(test_awt.Base):
    def setUp(self):
        super().setUp()
        self.top = os.path.join(self.tmp, "tree")
        os.mkdir(self.top)

    def mk(self, kind, name, parent, *extra, **kw):
        r = self.ok("init", "--kind", kind, "--name", name, *extra, root=parent, **kw)
        parts = r.stdout.split()
        self.assertEqual(parts[0], "init", r.stdout)
        self.assertEqual(parts[2], kind, r.stdout)
        return os.path.join(parent, parts[1])

    def make_root(self):
        self.ok("init", "--kind", "root", root=self.top)
        return self.top

    def chain(self):
        root = self.make_root()
        ws = self.mk("workspace", "Alpha", root)
        task = self.mk("task", "Fix login", ws, "--goal", "fix it", "--done", "merged")
        agent = self.mk("agent", "chat-1", task)
        sub = self.mk("agent", "sub-1", agent)
        return root, ws, task, agent, sub

    def rows_of(self, node, typ=None):
        with open(os.path.join(node, ".awt", "events.jsonl"), encoding="utf-8") as g:
            rs = [json.loads(x) for x in g.read().splitlines() if x.strip().startswith("{")]
        return [r for r in rs if typ is None or r["type"] == typ]

    def events_of(self, node):
        return test_awt.slurp(os.path.join(node, ".awt", "events.jsonl"), "rb")

    def refuses(self, *args, code=1, **kw):
        r = self.bad(*args, code=code, **kw)
        self.assertIn("error:", r.stderr)
        self.assertIn("fix:", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        return r


class Create(TreeBase):
    def test_root_layout(self):  # T1
        root = self.make_root()
        block = test_awt.slurp(os.path.join(root, "AGENTS.md"))
        self.assertIn("awt resume", block)
        self.assertNotIn("./awt", block)
        self.assertLessEqual(len(block.encode()), 2048)
        self.assertTrue(os.path.isdir(os.path.join(root, "workspaces")))
        self.assertTrue(os.path.isfile(os.path.join(root, "README.md")))
        self.assertFalse(os.path.exists(os.path.join(root, ".claude")))
        self.assertEqual(self.rows_of(root, "node")[0]["kind"], "root")
        self.ok("doctor", root=root)

    def test_chain_layout(self):  # T2
        root, ws, task, agent, sub = self.chain()
        self.assertEqual(ws, os.path.join(root, "workspaces", "alpha"))
        self.assertEqual(task, os.path.join(ws, "tasks", "fix-login"))
        self.assertEqual(agent, os.path.join(task, "agents", "chat-1"))
        self.assertEqual(sub, os.path.join(agent, "agents", "sub-1"))
        want = {ws: {"context", "docs", "misc"}, task: {"context", "docs", "outbox", "misc", "scratch"}, agent: {"scratch"}, sub: {"scratch"}}
        for node, dirs in want.items():
            have = set(os.listdir(node))
            self.assertTrue(dirs <= have, (node, have))
            for banned in ("AGENTS.md", "README.md", ".claude"):
                if node != task or banned == "README.md":
                    self.assertNotIn(banned, have, node)
            self.assertIn("scratch/", test_awt.slurp(os.path.join(node, ".gitignore")))
        for node, kind, name in ((ws, "workspace", "Alpha"), (task, "task", "Fix login"), (agent, "agent", "chat-1"), (sub, "agent", "sub-1")):
            first = self.rows_of(node)[0]
            self.assertEqual((first["type"], first["kind"], first["name"]), ("node", kind, name))
        self.assertEqual(self.rows_of(task, "task")[0]["goal"], "fix it")
        for node in (ws, task, agent, sub):
            self.ok("resume", root=node)

    def test_illegal_pairs(self):  # T3
        root, ws, task, agent, sub = self.chain()
        for kind, parent in (("task", root), ("agent", root), ("workspace", ws), ("workspace", task), ("agent", ws), ("task", agent), ("workspace", agent)):
            r = self.refuses("init", "--kind", kind, "--name", "x", "--goal", "g", "--done", "d", root=parent)
            self.assertRegex(r.stderr, r"legal|allowed|may contain")

    def test_missing_args(self):  # T4
        root = self.make_root()
        ws = self.mk("workspace", "a", root)
        self.bad("init", "--kind", "task", root=ws, code=2)
        r = self.refuses("init", "--kind", "task", "--name", "t", root=ws)
        self.assertIn("goal", r.stderr)
        self.assertEqual(os.listdir(os.path.join(ws, "tasks")) if os.path.isdir(os.path.join(ws, "tasks")) else [], [])
        self.bad("init", "--kind", "bogus", "--name", "t", root=ws, code=2)

    def test_key_is_idempotent(self):  # T5
        root = self.make_root()
        ws = self.mk("workspace", "a", root, "--key", "paseo:workspace/w1")
        before = self.events_of(root)
        again = self.mk("workspace", "a", root, "--key", "paseo:workspace/w1")
        self.assertEqual(ws, again)
        self.assertEqual(os.listdir(os.path.join(root, "workspaces")), ["a"])
        self.assertEqual(len(self.rows_of(ws, "node")), 1)
        self.assertEqual(before, self.events_of(root))

    def test_same_name_other_key_gets_suffix(self):  # T5
        root = self.make_root()
        a = self.mk("workspace", "x", root, "--key", "k1")
        b = self.mk("workspace", "x", root, "--key", "k2")
        c = self.mk("workspace", "x", root)
        self.assertEqual(sorted(os.path.basename(p) for p in (a, b, c)), ["x", "x-2", "x-3"])

    def test_same_key_other_name_returns_existing(self):  # T6
        root = self.make_root()
        a = self.mk("workspace", "first", root, "--key", "k1")
        b = self.mk("workspace", "second", root, "--key", "k1")
        self.assertEqual(a, b)
        self.assertEqual(self.rows_of(a, "node")[0]["name"], "first")

    def test_slug_never_escapes(self):  # T7
        root = self.make_root()
        ws = self.mk("workspace", "w", root)
        for name in ("../../etc", "a/b", ".hidden", "  spaces  ", "ÜñïçÖdé", "!!!", "x" * 60, "a\tb", "..", "."):
            r = self.awt("init", "--kind", "task", "--name", name, "--goal", "g", "--done", "d", root=ws)
            self.assertIn(r.returncode, (0, 1, 2), (name, r.stdout, r.stderr))
            self.assertNotIn("Traceback", r.stderr)
        for n in os.listdir(os.path.join(ws, "tasks")):
            self.assertRegex(n, r"^[a-z0-9-]{1,50}$")
        self.assertEqual(set(os.listdir(ws)) - {"tasks", "context", "docs", "misc", ".awt", ".gitignore"}, set())
        self.refuses("init", "--kind", "task", "--name", "x" * 500, "--goal", "g", "--done", "d", root=ws)

    def test_secret_in_name_or_key(self):  # T8
        root = self.make_root()
        ws = self.mk("workspace", "w", root)
        self.refuses("init", "--kind", "task", "--name", test_awt.AKIA, "--goal", "g", "--done", "d", root=ws)
        self.refuses("init", "--kind", "task", "--name", "ok", "--key", test_awt.AKIA, "--goal", "g", "--done", "d", root=ws)
        self.assertFalse(os.path.exists(os.path.join(ws, "tasks")) and os.listdir(os.path.join(ws, "tasks")))

    def test_leftover_new_dirs_are_ignored(self):
        root = self.make_root()
        os.makedirs(os.path.join(root, "workspaces", ".new-deadbeef", ".awt"))
        ws = self.mk("workspace", "w", root, "--key", "k")
        self.assertEqual(os.path.basename(ws), "w")

    def test_standalone_init_unchanged(self):  # T9
        root, ws, task, agent, sub = self.chain()
        plain = os.path.join(self.tmp, "plain")
        os.mkdir(plain)
        self.ok("init", "--goal", "g", "--done", "d", root=plain)
        for f in ("AGENTS.md", "README.md", ".claude/settings.json", "docs", "outbox"):
            self.assertTrue(os.path.exists(os.path.join(plain, f)), f)
        self.assertIn("./awt", test_awt.slurp(os.path.join(plain, "AGENTS.md")))
        self.assertEqual([r["type"] for r in self.rows_of(plain)], ["task"])


class Converting(TreeBase):
    def test_standalone_task_moved_into_workspace_becomes_child(self):  # T14
        root = self.make_root()
        ws = self.mk("workspace", "Alpha", root)
        solo = os.path.join(self.tmp, "solo")
        os.mkdir(solo)
        self.ok("init", "--goal", "port parser", "--done", "merged", root=solo)
        self.ok("note", "tokenizer is slow", root=solo)
        before = hashlib.sha256(self.events_of(solo)).hexdigest()
        dest = os.path.join(ws, "tasks", "solo")
        shutil.move(solo, dest)
        self.assertEqual(hashlib.sha256(self.events_of(dest)).hexdigest(), before)
        rows = json.loads(self.ok("list", "nodes", "--all", "--json", root=root).stdout)
        self.assertIn(os.path.join("workspaces", "alpha", "tasks", "solo"), [r["path"] for r in rows])
        out = self.ok("resume", root=dest).stdout
        self.assertRegex(out.split("## Lineage")[1].split("\n## ")[0], r"workspace Alpha")
        self.assertIn("workspace Alpha", out)
        self.assertIn("tokenizer is slow", self.ok("list", "notes", root=dest).stdout)
        self.assertIn("solo", self.ok("resume", root=ws).stdout.split("## Children")[1])
        self.assertEqual(hashlib.sha256(self.events_of(dest)).hexdigest(), before)  # reading changed nothing


class Edges(TreeBase):
    def test_later_node_row_is_quarantined_first_stands(self):  # T15
        root, ws, task, agent, sub = self.chain()
        before = self.rows_of(task, "node")
        self.assertEqual(len(before), 1)
        with open(os.path.join(task, ".awt", "events.jsonl"), "ab") as g:
            g.write((json.dumps(dict(v=1, ts=test_awt.ts(), host="h", by="t", type="node", kind="agent", name="Impostor", key="paseo:agent/impostor", parent=None)) + "\n").encode())
        rows = json.loads(self.ok("list", "nodes", "--all", "--json", root=root).stdout)
        t = [r for r in rows if r["path"].endswith("tasks/fix-login")]
        self.assertEqual([(r["kind"], r["name"]) for r in t], [("task", "Fix login")])
        self.assertNotIn("Impostor", self.ok("resume", root=task).stdout)
        self.assertEqual(json.loads(self.ok("list", "nodes", "--all", "--json", root=root).stdout), rows)
        self.assertRegex(self.ok("doctor", root=task).stdout, r"quarantined")
        self.assertNotRegex(self.ok("doctor", root=task).stdout, r"\b0 quarantined")


    """Where init meets a directory that already has records or a node."""
    def test_root_refused_on_dir_with_rows(self):
        d = os.path.join(self.tmp, "s")
        os.mkdir(d)
        self.ok("init", "--goal", "g", "--done", "d", root=d)
        before = self.events_of(d)
        r = self.refuses("init", "--kind", "root", root=d)
        self.assertIn("empty", r.stderr)
        self.assertEqual(before, self.events_of(d))
        self.assertFalse(os.path.exists(os.path.join(d, "workspaces")))

    def test_root_init_is_a_noop_again(self):
        root = self.make_root()
        before = self.events_of(root)
        self.ok("init", "--kind", "root", root=root)
        self.assertEqual(before, self.events_of(root))

    def test_init_refused_on_existing_nodes(self):
        root, ws, task, agent, sub = self.chain()
        for node in (ws, task, agent):
            before = sorted(os.listdir(node))
            self.refuses("init", "--kind", "root", root=node)
            self.refuses("init", root=node)
            self.refuses("init", "--goal", "g", "--done", "d", root=node)
            self.assertEqual(before, sorted(os.listdir(node)), node)
        self.refuses("init", root=root)
        self.assertNotIn("AGENTS.md", os.listdir(ws))

    def test_legacy_tasks_folder_still_listed(self):
        d = os.path.join(self.tmp, "s")
        os.mkdir(d)
        self.ok("init", "--goal", "g", "--done", "d", root=d)
        for rel in ("tasks/todo.txt", "agents/x.txt", "workspaces/y.txt"):
            os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
            with open(os.path.join(d, rel), "w") as g:
                g.write("hello\n")
        listing = self.ok("list", "misc", root=d).stdout
        for rel in ("tasks/todo.txt", "agents/x.txt", "workspaces/y.txt"):
            self.assertIn(rel, listing)

    def test_name_or_key_need_kind(self):
        d = os.path.join(self.tmp, "s2")
        os.mkdir(d)
        for flag in ("--name", "--key"):
            self.bad("init", flag, "x", root=d, code=2)
        self.assertFalse(os.path.exists(os.path.join(d, ".awt")))

    def test_name_cap_fix_is_about_names(self):
        root = self.make_root()
        r = self.refuses("init", "--kind", "workspace", "--name", "n" * 61, root=root)
        self.assertIn("at most 60", r.stderr)
        self.assertNotIn("docs/", r.stderr)

    def test_flock_unsupported_is_a_refusal(self):
        root = self.make_root()
        code = ("import errno, fcntl, runpy, sys\n"
                "def f(*a): raise OSError(errno.ENOTSUP, 'no flock')\n"
                "fcntl.flock = f\n"
                "sys.argv = ['awt'] + sys.argv[1:]\n"
                "runpy.run_path(%r, run_name='__main__')\n" % test_awt.AWT)
        r = subprocess.run([sys.executable, "-I", "-c", code, "--dir", root, "init", "--kind", "workspace", "--name", "w", "--key", "k"],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("local filesystem", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(root, "workspaces", "w")))

    def test_rename_takes_over_only_an_empty_dir(self):
        root = self.make_root()
        os.makedirs(os.path.join(root, "workspaces", "w"))
        os.makedirs(os.path.join(root, "workspaces", "v"))
        with open(os.path.join(root, "workspaces", "v", "keep"), "w") as g:
            g.write("x")
        self.assertEqual(self.mk("workspace", "w", root), os.path.join(root, "workspaces", "w"))
        v = self.mk("workspace", "v", root)
        self.assertEqual(os.path.basename(v), "v-2")
        self.assertTrue(os.path.exists(os.path.join(root, "workspaces", "v", "keep")))


class TreeKeys(TreeBase):
    def test_key_unique_across_depths(self):
        root, ws, task, agent, sub = self.chain()
        ws2 = self.mk("workspace", "Beta", root)
        t = self.mk("task", "Deep", ws, "--goal", "g", "--done", "d", "--key", "ext:1")
        before = self.events_of(root)
        for parent in (root, ws, ws2, task):
            kind = {root: "workspace", ws: "task", ws2: "task", task: "agent"}[parent]
            r = self.ok("init", "--kind", kind, "--name", "again", "--key", "ext:1", "--goal", "g", "--done", "d", root=parent)
            parts = r.stdout.split()
            self.assertEqual(os.path.realpath(os.path.join(parent, parts[1])), os.path.realpath(t), r.stdout)
            self.assertEqual(parts[2], "task")
        self.assertEqual(self.rows_of(t, "node")[0]["name"], "Deep")
        self.assertEqual(before, self.events_of(root))
        self.assertFalse(os.path.exists(os.path.join(ws2, "tasks")) and os.listdir(os.path.join(ws2, "tasks")))

    def test_key_found_from_a_deep_agent(self):
        root, ws, task, agent, sub = self.chain()
        k = self.mk("workspace", "K", root, "--key", "ext:top")
        r = self.ok("init", "--kind", "agent", "--name", "z", "--key", "ext:top", root=sub)
        self.assertEqual(os.path.realpath(os.path.join(sub, r.stdout.split()[1])), os.path.realpath(k))


class Resolve(TreeBase):
    def test_cwd_env_dir_precedence(self):  # T10
        root, ws, task, agent, sub = self.chain()
        self.ok("note", "from cwd", root="", cwd=agent)
        self.assertEqual([r["text"] for r in self.rows_of(agent, "note")], ["from cwd"])
        env = dict(self.env, AWT_DIR=task)
        self.ok("note", "from env", root="", cwd=agent, env=env)
        self.assertEqual([r["text"] for r in self.rows_of(task, "note")], ["from env"])
        self.ok("note", "from flag", root=ws, cwd=agent, env=env)
        self.assertEqual([r["text"] for r in self.rows_of(ws, "note")], ["from flag"])

    def test_bad_awt_dir(self):  # T11
        root, ws, task, agent, sub = self.chain()
        env = dict(self.env, AWT_DIR=os.path.join(task, "docs"))
        r = self.bad("note", "x", root="", cwd=task, env=env, code=4)
        self.assertIn("fix:", r.stderr)

    def test_by_is_stamped(self):  # T51
        root, ws, task, agent, sub = self.chain()
        env = dict(self.env, AWT_DIR=agent, AWT_BY="agt_42")
        self.ok("note", "hi", root="", env=env)
        self.assertEqual(self.rows_of(agent, "note")[0]["by"], "agt_42")


class Isolation(TreeBase):
    def test_child_nodes_are_not_files_of_the_parent(self):
        root, ws, task, agent, sub = self.chain()
        self.write_in(sub, "docs/n.md", "needle in a haystack\n")
        self.write_in(agent, "scratch/x.txt", "needle\n")
        for node in (root, ws, task):
            r = self.ok("find", "needle", root=node)
            self.assertNotIn("needle", r.stdout, node)
            listing = self.ok("list", "misc", root=node).stdout
            for name in ("workspaces", "tasks", "agents"):
                self.assertNotIn(name, listing, node)
        r = self.ok("find", "needle", root=sub)
        self.assertIn("n.md", r.stdout)

    def write_in(self, node, rel, text):
        p = os.path.join(node, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as g:
            g.write(text)

    def test_changes_section_ignores_child_nodes(self):
        root, ws, task, agent, sub = self.chain()
        self.ok("state", "--now", "n", "--next", "x", root=task)
        self.write_in(sub, "docs/late.md", "late\n")
        self.assertNotIn("late.md", self.ok("resume", root=task).stdout)

    def test_task_node_has_tree_contract_and_hook(self):  # T2
        root, ws, task, agent, sub = self.chain()
        block = test_awt.slurp(os.path.join(task, "AGENTS.md"))
        self.assertIn("awt resume", block)
        self.assertNotIn("./awt", block)
        st = test_awt.slurp(os.path.join(task, ".claude", "settings.json"))
        self.assertIn("awt resume --hook", st)
        self.assertNotIn("/awt resume", st)
        self.assertFalse(os.path.exists(os.path.join(task, "README.md")))
        for node in (root, ws, agent):
            self.assertFalse(os.path.exists(os.path.join(node, ".claude")), node)
        self.ok("doctor", root=task)

    def test_key_search_stops_at_first_root(self):
        root, ws, task, agent, sub = self.chain()
        t2 = self.mk("task", "Other", ws, "--goal", "g", "--done", "d", "--key", "k:outer")
        inner = os.path.join(task, "agents", "inner-tree")
        os.makedirs(inner)
        self.ok("init", "--kind", "root", "--dir", inner)
        iw = self.mk("workspace", "Beta", inner)
        r = self.ok("init", "--kind", "task", "--name", "Dup", "--goal", "g", "--done", "d", "--key", "k:outer", root=iw)
        self.assertNotIn(os.path.basename(t2), r.stdout)
        self.assertEqual(len(self.rows_of(os.path.join(iw, r.stdout.split()[1]), "node")), 1)

    def test_misc_listing_skips_nested_nodes(self):
        root, ws, task, agent, sub = self.chain()
        inner = os.path.join(task, "misc", "side")
        os.makedirs(inner)
        self.ok("init", root=inner)
        self.write_in(inner, "docs/theirs.md", "# theirs\n")
        self.write_in(task, "misc/mine.md", "# mine\n")
        out = self.ok("list", "misc", root=task).stdout
        self.assertIn("mine.md", out)
        self.assertNotIn("theirs.md", out)

    def test_parallel_agents_keep_their_own_logs(self):  # T50
        root, ws, task, agent, sub = self.chain()
        agents = [self.mk("agent", "a%d" % i, task) for i in range(20)]

        def work(i):
            env = dict(self.env, AWT_DIR=agents[i], AWT_BY="agt_%d" % i)
            for j in range(50):
                r = subprocess.run([sys.executable, "-I", test_awt.AWT, "note", "n-%d-%d" % (i, j)], env=env, capture_output=True, text=True, cwd=self.tmp)
                if r.returncode:
                    return r.stderr
            return ""
        with cf.ThreadPoolExecutor(20) as ex:
            self.assertEqual(list(ex.map(work, range(20))), [""] * 20)
        for i, node in enumerate(agents):
            notes = self.rows_of(node, "note")
            self.assertEqual(sorted(r["text"] for r in notes), sorted("n-%d-%d" % (i, j) for j in range(50)))
            self.assertEqual({r["by"] for r in notes}, {"agt_%d" % i})
        self.assertEqual(self.rows_of(task, "note"), [])


if __name__ == "__main__":
    unittest.main()
