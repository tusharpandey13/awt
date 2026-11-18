"""Child nodes and the subagent-row link (docs/spec-child-nodes.md; SPEC.md, "Node tree" and "Detected effects"). Every check runs the real awt in a temp HOME."""
import json, os, shlex, shutil, sqlite3, subprocess, sys, textwrap, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_awt
from test_ingest import SID, rec
from test_providers import Prov
from test_store import result, tool_use
from test_tree import TreeBase

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")


def claude(name, tool, inp, tid="toolu_X", **extra):
    return dict(hook_event_name=name, tool_name=tool, tool_input=inp, tool_use_id=tid, cwd="/work/parsekit", **extra)


def brief(key, line=2):
    lines = ["Scan the repo for TODOs."] + ["More detail."] * (line - 2)
    lines.insert(line - 1, "RUN_KEY: %s" % key)
    return "\n".join(lines) + "\nDone when listed.\n"


class Child(TreeBase):
    def setUp(self):
        super().setUp()
        self.root_, self.ws, self.task, self.agent, self.sub = self.chain()

    def child(self, key="scan-1", parent=None, *extra):
        return self.ok("init", "--child", key, *extra, root=parent or self.task)

    def cpath(self, key="scan-1", parent=None):
        return os.path.join(parent or self.task, "agents", key)

    def hook(self, payload, root=None, **kw):
        r = self.ok("ingest", "--event", "--hook", root=root or self.task, input=json.dumps(payload), **kw)
        self.assertEqual((r.stdout, r.stderr), ("", ""))
        return r

    def launch(self, key="scan-1", tid="toolu_X", tool="Agent", **kw):
        return self.hook(claude("PreToolUse", tool, {"description": "d", "prompt": brief(key)}, tid), **kw)

    def refs(self, node):
        return self.rows_of(node, "ref")

    def status(self, node):
        s = [r["status"] for r in self.rows_of(node, "status")]
        return s[-1] if s else "active"


class Create(Child):
    def test_cn1_creates_the_node(self):
        r = self.child()
        p = self.cpath()
        self.assertEqual(r.stdout, "AWT_DIR=%s AWT_BY=sub:scan-1\n" % shlex.quote(os.path.realpath(p)))
        self.assertEqual(r.stderr, "")
        (n,) = self.rows_of(p, "node")
        self.assertEqual((n["kind"], n["name"], n["run"]), ("agent", "scan-1", "scan-1"))
        self.assertNotIn("key", n)
        self.assertEqual(self.rows_of(p, "task")[0]["goal"], "scan-1")
        self.assertTrue(os.path.isfile(os.path.join(p, "BRIEF.md")))

    def test_cn1_goal_and_done_are_optional(self):
        self.child("scan-2", None, "--goal", "find todos", "--done", "listed")
        self.assertEqual(self.rows_of(self.cpath("scan-2"), "task")[0]["goal"], "find todos")
        self.bad("init", "--child", "scan-3", "--goal", "x", root=self.task, code=2)

    def test_cn1_under_an_agent(self):
        r = self.child("deep-1", self.agent)
        self.assertTrue(os.path.isdir(os.path.join(self.agent, "agents", "deep-1", ".awt")))
        self.assertIn("AWT_BY=sub:deep-1", r.stdout)

    def test_cn1_dir_beats_awt_dir(self):
        env = dict(self.env, AWT_DIR=self.agent)
        self.ok("init", "--child", "k-1", root=self.task, env=env)
        self.assertTrue(os.path.isdir(self.cpath("k-1")))
        self.ok("init", "--child", "k-2", root="", env=env)  # AWT_DIR alone names the parent
        self.assertTrue(os.path.isdir(os.path.join(self.agent, "agents", "k-2")))

    def test_cn2_again_changes_nothing(self):
        first = self.child()
        snap = self.events_of(self.cpath())
        r = self.child()
        self.assertEqual(r.stdout, first.stdout)
        self.assertEqual(r.stderr, "note: child node agents/scan-1 already exists\n")
        self.assertEqual(self.events_of(self.cpath()), snap)
        self.assertEqual(len(self.rows_of(self.cpath(), "node")), 1)

    def test_cn3_invalid_keys(self):
        for k in ("Scan", "../x", "a/b", "-x", "a" * 41, "", "a b", "x.y"):
            with self.subTest(key=k):
                r = self.bad("init", "--child=" + k, root=self.task, code=2)
                self.assertIn("fix: use lowercase letters, digits and -", r.stderr)
        self.assertEqual(sorted(os.listdir(os.path.join(self.task, "agents"))), ["chat-1"])
        self.ok("init", "--child", "a" * 40, root=self.task)
        r = self.bad("init", "--child", "../x", root="", code=2)  # a bad key is a usage error even with no parent node
        self.assertIn("fix: use lowercase letters, digits and -", r.stderr)

    def test_cn4_parent_kinds(self):
        for node in (self.root_, self.ws):
            r = self.refuses("init", "--child", "k", root=node)
            self.assertIn("may contain", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "agents")))
        legacy = os.path.join(self.tmp, "legacy")
        os.mkdir(legacy)
        self.ok("init", "--goal", "g", "--done", "d", root=legacy)
        r = self.ok("init", "--child", "k", root=legacy)
        self.assertIn("AWT_BY=sub:k", r.stdout)
        self.assertEqual(self.rows_of(os.path.join(legacy, "agents", "k"), "node")[0]["run"], "k")

    def test_cn5_the_target_is_something_else(self):
        agents = os.path.join(self.task, "agents")
        for what in ("node", "file", "dir", "link"):
            with self.subTest(what=what):
                p = os.path.join(agents, "x-" + what)
                if what == "node":
                    self.mk("agent", "x-node", self.task)
                elif what == "file":
                    with open(p, "w") as g:
                        g.write("hi")
                elif what == "dir":
                    os.mkdir(p)
                    with open(os.path.join(p, "f"), "w") as g:
                        g.write("hi")
                else:
                    os.symlink(self.agent, p)
                r = self.refuses("init", "--child", "x-" + what, root=self.task)
                self.assertIn("fix: pick another RUN_KEY", r.stderr)
        self.assertEqual([x for x in os.listdir(agents) if x.startswith(".new")], [])
        os.mkdir(os.path.join(agents, "empty-1"))
        self.child("empty-1")
        self.assertEqual(self.rows_of(self.cpath("empty-1"), "node")[0]["run"], "empty-1")

    def test_cn5_agents_symlink_is_refused(self):
        other = os.path.join(self.tmp, "other")
        os.mkdir(other)
        os.rename(os.path.join(self.task, "agents"), os.path.join(self.tmp, "gone"))
        os.symlink(other, os.path.join(self.task, "agents"))
        self.refuses("init", "--child", "k", root=self.task)
        self.assertEqual(os.listdir(other), [])

    def test_cn6_does_not_combine(self):
        for extra in (("--kind", "agent"), ("--name", "x"), ("--key", "k"), ("--hooks", "claude")):
            with self.subTest(extra=extra):
                self.bad("init", "--child", "k", *extra, root=self.task, code=2)
        self.assertFalse(os.path.exists(self.cpath("k")))


class Writes(Child):
    def test_cn7_parallel_children_do_not_collide(self):
        a, b = self.cpath("a-1"), self.cpath("b-1")
        self.child("a-1")
        self.child("b-1")
        env = dict(self.env, AWT_BY="parent-agent")
        for k, node in (("a", a), ("b", b)):
            with open(os.path.join(node, "out.md"), "w") as g:
                g.write("result %s\n" % k)
            self.ok("note", "from %s" % k, root="", env=dict(env, AWT_DIR=node))
        self.assertEqual(test_awt.slurp(os.path.join(a, "out.md")), "result a\n")
        self.assertEqual(test_awt.slurp(os.path.join(b, "out.md")), "result b\n")
        self.assertEqual([r["by"] for r in self.rows_of(a, "note")], ["sub:a-1"])
        self.assertEqual([r["by"] for r in self.rows_of(b, "note")], ["sub:b-1"])
        self.assertEqual(self.rows_of(self.task, "note"), [])

    def test_cn8_by_flag_wins_and_other_nodes_keep_awt_by(self):
        self.child()
        env = dict(self.env, AWT_BY="parent-agent")
        c = self.cpath()
        self.ok("--by", "hook", "note", "h", root=c, env=env)
        self.ok("--by", "person", "note", "p", root=c, env=env)
        self.ok("note", "d", root=c, env=env)
        self.ok("note", "t", root=self.task, env=env)
        self.assertEqual([r["by"] for r in self.rows_of(c, "note")], ["hook", "person", "sub:scan-1"])
        self.assertEqual([r["by"] for r in self.rows_of(self.task, "note")], ["parent-agent"])

    def test_cn8_every_verb_stamps_the_child(self):
        self.child()
        c = self.cpath()
        env = dict(self.env, AWT_BY="parent-agent")
        self.ok("ask", "q?", root=c, env=env)
        self.ok("decide", "x", "--why", "y", root=c, env=env)
        self.ok("ref", "https://example.com/a", "--title", "t", root=c, env=env)
        self.assertEqual({r["by"] for r in self.rows_of(c) if r["type"] in ("question", "decision", "ref")}, {"sub:scan-1"})

    def test_ref_infers_the_tool_call_kind(self):
        self.child()
        c = self.cpath()
        self.ok("ref", "tool-call:toolu_Q", "--title", "scan-1", root=c)
        (r,) = self.refs(c)
        self.assertEqual((r["kind"], r["access"], r["target"], r["title"]), ("tool-call", "ok", "tool-call:toolu_Q", "scan-1"))


class Reads(Child):
    def test_cn9_doctor(self):
        self.child("a-1")
        self.child("b-1")
        r = self.ok("doctor", root=self.task)
        self.assertNotRegex(r.stdout, r"(?m)^fail")
        os.rename(self.cpath("a-1"), self.cpath("zzz"))
        r = self.bad("doctor", root=self.task)
        self.assertRegex(r.stdout, r"(?m)^fail.*agents/zzz")
        self.assertIn("a-1", r.stdout)

    def test_t3_run_outside_agents_fails_and_a_non_agent_warns(self):
        self.child()
        row = self.rows_of(self.cpath(), "node")[0]
        t2 = os.path.join(self.ws, "tasks", "t2")
        os.makedirs(os.path.join(t2, ".awt"))
        with open(os.path.join(t2, ".awt", "events.jsonl"), "w") as g:
            g.write(json.dumps(dict(row, kind="task", name="t2")) + "\n")
        r = self.bad("doctor", root=self.ws)
        self.assertRegex(r.stdout, r"(?m)^warn.*tasks/t2.*run")
        self.assertRegex(r.stdout, r"(?m)^fail.*tasks/t2.*agents")

    def test_cn10_resume_and_find(self):
        for k in ("a-1", "b-1"):
            self.child(k)
            self.ok("note", "zorblax %s" % k, root=self.cpath(k))
            with open(os.path.join(self.cpath(k), "out.md"), "w") as g:
                g.write("x" * 100)
        r = self.ok("resume", root=self.task)
        for k in ("a-1", "b-1"):
            self.assertIn(k, r.stdout)
        f = self.ok("find", "--down", "zorblax", root=self.task)
        self.assertIn("agents/a-1:", f.stdout)
        self.assertIn("agents/b-1:", f.stdout)

    def test_t4_list_nodes_json_has_run(self):
        self.child()
        rows = json.loads(self.ok("list", "nodes", "--json", root=self.task).stdout)
        by = {r["name"]: r for r in rows}
        self.assertEqual(by["scan-1"]["run"], "scan-1")
        self.assertIsNone(by["chat-1"]["run"])

    def test_cn11_older_awt_reads_a_child_node(self):
        old = os.path.join(self.tmp, "awt-old")
        r = subprocess.run(["git", "show", "v0.3.1:awt"], cwd=ROOT, capture_output=True)
        if r.returncode != 0:
            self.skipTest("tag v0.3.1 is not in this clone")
        with open(old, "wb") as g:
            g.write(r.stdout)
        self.child()
        self.ok("note", "hello", root=self.cpath())

        def run(*args, node=self.task):
            p = subprocess.run([sys.executable, "-I", old, "--dir", node] + list(args), capture_output=True, text=True, env=self.env)
            self.assertEqual(p.returncode, 0, (args, p.stdout, p.stderr))
            self.assertNotRegex(p.stdout + p.stderr, r"[1-9]\d* quarantined")
            return p.stdout
        run("resume")
        run("doctor")
        self.assertIn("agent scan-1", run("list", "nodes"))
        self.assertIn("hello", run("list", "notes", node=self.cpath()))


class Hooked(Child):
    def test_cl1_claude_launch_creates_node_and_link(self):
        self.launch()
        c = self.cpath()
        (n,) = self.rows_of(c, "node")
        self.assertEqual(n["run"], "scan-1")
        (r,) = self.refs(c)
        self.assertEqual((r["target"], r["title"], r["kind"], r["access"], r["by"]), ("tool-call:toolu_X", "scan-1", "tool-call", "ok", "hook"))
        self.assertEqual(self.rows_of(self.task, "effect") + self.rows_of(c, "effect"), [])
        self.launch()  # a replay changes nothing
        self.assertEqual(len(self.refs(c)), 1)
        self.assertEqual(len(self.rows_of(c, "node")), 1)
        self.launch("scan-1", "toolu_Z")  # a second call under the same key: a second link, one node
        self.assertEqual(sorted(r["target"] for r in self.refs(c)), ["tool-call:toolu_X", "tool-call:toolu_Z"])

    def test_cl1_task_tool_name_too(self):
        self.launch(tool="Task")
        self.assertTrue(os.path.isdir(self.cpath()))

    def test_cl1_node_from_awt_dir(self):
        r = self.ok("ingest", "--event", "--hook", root="", input=json.dumps(claude("PreToolUse", "Agent", {"prompt": brief("env-1")})), env=dict(self.env, AWT_DIR=self.task))
        self.assertEqual(r.stdout, "")
        self.assertTrue(os.path.isdir(self.cpath("env-1")))

    def test_cl2_no_node_without_a_valid_key(self):
        for prompt in ("no key here", brief("scan-1", 7), brief("Bad_Key"), "RUN_KEY: " + "a" * 41, "RUN_KEY: scan-1 trailing", "quoted RUN_KEY: scan-1"):
            with self.subTest(prompt=prompt[:30]):
                self.hook(claude("PreToolUse", "Agent", {"prompt": prompt}))
        self.hook(claude("PreToolUse", "Agent", {"description": "d"}))
        self.hook(claude("PreToolUse", "Agent", {"prompt": 5}))
        self.assertEqual(sorted(os.listdir(os.path.join(self.task, "agents"))), ["chat-1"])

    def test_cl2_under_a_workspace_nothing(self):
        self.hook(claude("PreToolUse", "Agent", {"prompt": brief("scan-1")}), root=self.ws)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "agents")))

    def test_cl2_not_a_launch(self):
        self.hook(claude("PreToolUse", "Read", {"prompt": brief("scan-1")}))
        self.hook(claude("PreToolUse", "Bash", {"command": "echo hi", "prompt": brief("scan-1")}))
        self.assertFalse(os.path.exists(self.cpath()))

    def test_cl3_pi_launch(self):
        def ev(inp, tid="call_Y"):
            return dict(phase="before", tool="subagent", input=inp, id=tid, cwd="/w")
        self.hook(ev({"agent": "general", "task": brief("pi-1")}))
        (r,) = self.refs(self.cpath("pi-1"))
        self.assertEqual(r["target"], "tool-call:call_Y")
        self.hook(ev({"action": "status", "task": brief("pi-2")}))
        self.hook(ev({"action": "resume", "id": "x", "task": brief("pi-3")}, "call_R"))
        self.assertFalse(os.path.exists(self.cpath("pi-2")))
        self.assertEqual(self.refs(self.cpath("pi-3"))[0]["target"], "tool-call:call_R")

    def test_cl3_parallel_tasks_get_one_node_each(self):
        self.hook(dict(phase="before", tool="subagent", id="call_P", cwd="/w", input={"tasks": [{"agent": "g", "task": brief("par-1")}, {"agent": "g", "task": brief("par-2")}, {"task": "no key"}]}))
        for k in ("par-1", "par-2"):
            self.assertEqual([r["target"] for r in self.refs(self.cpath(k))], ["tool-call:call_P"])
        self.assertEqual(sorted(os.listdir(os.path.join(self.task, "agents"))), ["chat-1", "par-1", "par-2"])

    def test_cl4_find_by_either_value(self):
        self.launch()
        self.ok("note", "zorblax elsewhere", root=self.agent)
        for term in ("toolu_X", "scan-1"):
            with self.subTest(term=term):
                r = self.ok("find", "--tree", term, root=self.task)
                self.assertIn("agents/scan-1:", r.stdout)
        self.assertIn("zorblax", self.ok("find", "--tree", "zorblax", root=self.task).stdout)
        self.assertNotIn("scan-1", self.ok("find", "--tree", "toolu_NOPE", root=self.task).stdout)
        self.assertEqual(json.loads(self.ok("list", "refs", "--json", root=self.cpath()).stdout)[0]["target"], "tool-call:toolu_X")

    def post(self, status="completed", **resp):
        return self.hook(claude("PostToolUse", "Agent", {"prompt": brief("scan-1")}, "toolu_X", tool_response=dict(status=status, **resp)))

    def test_cl5_done_on_a_finished_call(self):
        self.launch()
        self.post()
        self.assertEqual(self.status(self.cpath()), "done")
        self.assertEqual(self.rows_of(self.cpath(), "status")[-1]["by"], "hook")

    def test_cl5_paused_with_open_work(self):
        self.launch()
        self.ok("ask", "still open?", root=self.cpath())
        self.post()
        self.assertEqual(self.status(self.cpath()), "paused")

    def test_cl5_async_and_failures_change_nothing(self):
        self.launch()
        self.post("async_launched", isAsync=True)
        self.post("failed")
        self.hook(claude("PostToolUseFailure", "Agent", {"prompt": brief("scan-1")}, "toolu_X"))
        self.assertEqual(self.status(self.cpath()), "active")
        self.hook(dict(phase="after", tool="subagent", input={"task": brief("scan-1"), "async": True}, id="c", ok=True, cwd="/w"))
        self.assertEqual(self.status(self.cpath()), "active")
        self.hook(dict(phase="after", tool="subagent", input={"task": brief("scan-1")}, id="c", ok=True, cwd="/w"))
        self.assertEqual(self.status(self.cpath()), "done")

    def test_cl5_no_node_no_write(self):
        self.post()
        self.assertFalse(os.path.exists(self.cpath()))

    def test_cl5_never_finishes_through_a_symlink(self):
        other = os.path.join(self.tmp, "other")
        os.mkdir(other)
        self.ok("init", "--goal", "g", "--done", "d", root=other)
        self.child(parent=other)
        foreign = self.cpath(parent=other)
        shutil.rmtree(os.path.join(self.task, "agents"))
        os.symlink(os.path.join(other, "agents"), os.path.join(self.task, "agents"))  # agents/ itself (CH-5)
        self.post()
        self.assertEqual(self.status(foreign), "active")
        os.remove(os.path.join(self.task, "agents"))
        os.mkdir(os.path.join(self.task, "agents"))
        os.symlink(foreign, self.cpath())  # the slot
        self.post()
        self.assertEqual(self.status(foreign), "active")

    def test_cl6_done_with_the_parent(self):
        self.child("a-1")
        self.child("b-1")
        r = self.ok("status", "done", root=self.task)
        self.assertEqual((self.status(self.cpath("a-1")), self.status(self.cpath("b-1")), self.status(self.task)), ("done", "done", "done"))
        self.assertIn("status done", r.stdout)
        self.assertEqual(self.rows_of(self.cpath("a-1"), "status")[-1]["by"], "agent")  # the caller signs, not the child's own name

    def test_cl6_open_work_in_a_child_still_blocks(self):
        self.child("a-1")
        self.child("b-1")
        self.ok("ask", "open?", root=self.cpath("b-1"))
        self.refuses("status", "done", root=self.task)
        self.assertEqual((self.status(self.cpath("a-1")), self.status(self.cpath("b-1")), self.status(self.task)), ("active", "active", "active"))

    def test_cl6_only_active_child_nodes(self):
        self.child("a-1")
        self.ok("status", "paused", root=self.cpath("a-1"))
        self.ok("status", "done", root=self.task)
        self.assertEqual(self.status(self.cpath("a-1")), "paused")  # not active: left as it was
        self.assertEqual(self.status(self.agent), "active")  # a plain agent node is not a child node

    def test_cl6_a_child_parent_signs_as_itself(self):
        self.child("a-1")
        self.child("g-1", self.cpath("a-1"))
        self.ok("status", "done", root=self.cpath("a-1"), env=dict(self.env, AWT_BY="paseo:agent/parent"))
        self.assertEqual(self.rows_of(self.cpath("g-1", self.cpath("a-1")), "status")[-1]["by"], "sub:a-1")


class Install(test_awt.Base):
    def setUp(self):
        super().setUp()
        self.cfg = os.path.join(self.tmp, "claude-cfg")
        self.env.update(CLAUDE_CONFIG_DIR=self.cfg)
        self.settings = os.path.join(self.cfg, "settings.json")

    def load(self):
        return json.loads(test_awt.slurp(self.settings))

    def marks(self, st):
        res = {}
        for ev, es in st["hooks"].items():
            for e in es:
                for h in e["hooks"]:
                    for m in ("awt:child-guard", "awt:child", "awt:context"):
                        if h["command"].rstrip().endswith("# " + m):
                            res.setdefault(m, []).append((ev, e.get("matcher")))
        return res

    def test_cl7_install_idempotent_uninstall(self):
        other = {"type": "command", "command": "echo mine"}
        os.makedirs(self.cfg)
        with open(self.settings, "w") as g:
            json.dump({"hooks": {"PreToolUse": [{"matcher": "Agent|Task", "hooks": [other]}]}}, g)
        self.ok("init", "--hooks", "claude", root="")
        m = self.marks(self.load())
        self.assertEqual(sorted(m["awt:child"]), [("PostToolUse", "Agent|Task"), ("PreToolUse", "Agent|Task")])
        self.assertEqual(m["awt:child-guard"], [("PreToolUse", "Bash")])
        self.assertEqual(len(m["awt:context"]), 2)
        self.assertIn(other, [h for e in self.load()["hooks"]["PreToolUse"] for h in e["hooks"]])
        before = test_awt.slurp(self.settings)
        r = self.ok("init", "--hooks", "claude", root="")
        self.assertIn("unchanged", r.stdout)
        self.assertEqual(test_awt.slurp(self.settings), before)
        self.ok("init", "--hooks", "claude", "--uninstall", root="")
        st = self.load()
        self.assertEqual(self.marks(st), {})
        self.assertEqual(st["hooks"]["PreToolUse"], [{"matcher": "Agent|Task", "hooks": [other]}])

    def test_cl7_child_hook_is_silent_without_awt_dir(self):
        self.ok("init", "--hooks", "claude", root="")
        cmd = next(h["command"] for e in self.load()["hooks"]["PreToolUse"] for h in e["hooks"] if h["command"].rstrip().endswith("# awt:child"))
        self.assertTrue(cmd.startswith('[ -n "$AWT_DIR" ] || exit 0;'), cmd)
        r = subprocess.run(["sh", "-c", cmd], input=json.dumps(claude("PreToolUse", "Agent", {"prompt": brief("k-1")})), capture_output=True, text=True, env=self.env)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_cl7_child_hook_prefilter_skips_other_calls(self):
        self.ok("init", "--hooks", "claude", root="")
        cmd = next(h["command"] for e in self.load()["hooks"]["PreToolUse"] for h in e["hooks"] if h["command"].rstrip().endswith("# awt:child"))
        marker = os.path.join(self.tmp, "ran")
        fake = os.path.join(self.tmp, "bin")
        os.makedirs(fake)
        with open(os.path.join(fake, "awt"), "w") as g:
            g.write("#!/bin/sh\ntouch %s\n" % shlex.quote(marker))
        os.chmod(os.path.join(fake, "awt"), 0o755)
        cmd = cmd.replace(shlex.quote(test_awt.AWT), shlex.quote(os.path.join(fake, "awt")))
        env = dict(self.env, AWT_DIR=self.tmp)
        subprocess.run(["sh", "-c", cmd], input=json.dumps(claude("PreToolUse", "Agent", {"prompt": "no key"})), capture_output=True, text=True, env=env)
        self.assertFalse(os.path.exists(marker))
        subprocess.run(["sh", "-c", cmd], input=json.dumps(claude("PreToolUse", "Agent", {"prompt": brief("k-1")})), capture_output=True, text=True, env=env)
        self.assertTrue(os.path.exists(marker))

    def test_c9_task_settings_carry_the_new_matcher_and_prefilter(self):
        self.ok("init", "--goal", "g", "--done", "d")
        st = json.loads(test_awt.slurp(self.p(".claude", "settings.json")))
        for ev in ("PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionDenied"):
            self.assertEqual(st["hooks"][ev][0]["matcher"], "Bash|mcp__.*|Agent|Task")
        self.assertIn("RUN_KEY:", st["hooks"]["PreToolUse"][0]["hooks"][0]["command"])


class Guard(Child):
    def bash(self, cmd, env=None, **extra):
        payload = claude("PreToolUse", "Bash", {"command": cmd}, "toolu_B", **extra)
        r = self.ok("ingest", "--event", "--hook", root="", input=json.dumps(payload), env=dict(self.env, AWT_DIR=self.task) if env is None else env)
        self.assertEqual(r.stderr, "")
        return r.stdout

    def test_cl9_warns_a_subagent_without_dir(self):
        out = json.loads(self.bash("awt note x", agent_id="agent-1", agent_type="general"))
        h = out["hookSpecificOutput"]
        self.assertEqual(h["hookEventName"], "PreToolUse")
        self.assertIn("fix: pass --dir <your awt-node> on every call of awt", h["additionalContext"])
        self.assertNotIn("permissionDecision", h)
        for verb in ("note", "ask", "decide", "ref", "effect"):
            self.assertIn("additionalContext", self.bash("cd x && awt %s a" % verb, agent_id="a1"))
        for cmd in ("awt --by=sub:k note a", "awt --model=m1 note a", "awt --by x --model=m note a"):
            self.assertIn("additionalContext", self.bash(cmd, agent_id="a1"), cmd)

    def test_cl9_silent_cases(self):
        self.assertEqual(self.bash("awt note x --dir /p/agents/k", agent_id="a1"), "")
        self.assertEqual(self.bash("awt --dir /p note x", agent_id="a1"), "")
        self.assertEqual(self.bash("awt note x"), "")  # not a subagent
        self.assertEqual(self.bash("awt note x", agent_id="a1", env=dict(self.env)), "")  # AWT_DIR unset
        self.assertEqual(self.bash("awt resume", agent_id="a1"), "")
        self.assertEqual(self.bash("awt find note", agent_id="a1"), "")
        self.assertEqual(self.bash("echo awt notebook", agent_id="a1"), "")
        self.assertEqual(self.bash("ls", agent_id="a1"), "")

    def test_cl9_only_the_before_phase(self):
        r = self.ok("ingest", "--event", "--hook", root="", input=json.dumps(claude("PostToolUse", "Bash", {"command": "awt note x"}, agent_id="a1")), env=dict(self.env, AWT_DIR=self.task))
        self.assertEqual(r.stdout, "")


@unittest.skipUnless(NODE, "node is not installed")
class PiExt(Child):
    """The generated pi extension against a fake host (no model, no network): C10, C11, CL-8, CL-10."""

    def setUp(self):
        super().setUp()
        self.pi = os.path.join(self.tmp, "pi")
        self.env.update(PI_CODING_AGENT_DIR=self.pi)
        self.ok("init", "--hooks", "pi", root="")
        self.script = os.path.join(self.tmp, "drive.mjs")
        self.ext = "file://" + os.path.join(self.pi, "extensions", "awt-context.ts")

    def drive(self, body, env=None):
        text = textwrap.dedent("""
            import ext from %s
            const on = {}
            ext({ on: (n, f) => { on[n] = f } })
        """) % json.dumps(self.ext) + textwrap.dedent(body)
        with open(self.script, "w") as g:
            g.write(text)
        e = {k: v for k, v in self.env.items() if k not in ("AWT_DIR", "AWT_BY", "AWT_MODEL")}
        e.update(env or {})
        r = subprocess.run([NODE, "--experimental-strip-types", "--no-warnings", self.script], capture_output=True, text=True, env=e, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_cl8_parent_side_pipes_the_launch(self):
        res = self.drive("""
            await on.tool_call({ toolName: "subagent", toolCallId: "call_Y", input: { agent: "g", task: %s } }, {})
            await on.tool_call({ toolName: "bash", toolCallId: "call_B", input: { command: "ls" } }, {})
            console.log(JSON.stringify({ ok: true }))
        """ % json.dumps(brief("pi-1")), env=dict(AWT_DIR=self.task))
        self.assertTrue(res["ok"])
        (r,) = self.refs(self.cpath("pi-1"))
        self.assertEqual(r["target"], "tool-call:call_Y")
        self.assertEqual(sorted(os.listdir(os.path.join(self.task, "agents"))), ["chat-1", "pi-1"])

    def test_cl8_parent_side_does_nothing_in_a_child_or_without_a_node(self):
        body = """
            await on.tool_call({ toolName: "subagent", toolCallId: "call_Y", input: { task: %s } }, {})
            console.log(JSON.stringify({ ok: true }))
        """ % json.dumps(brief("pi-2"))
        self.drive(body, env=dict(AWT_DIR=self.task, PI_SUBAGENT_CHILD="1"))
        self.drive(body)
        self.assertFalse(os.path.exists(self.cpath("pi-2")))

    def test_cl8_parent_side_survives_a_failing_awt(self):
        res = self.drive("""
            await on.tool_call({ toolName: "subagent", toolCallId: "c", input: { task: "RUN_KEY: x-1" } }, {})
            console.log(JSON.stringify({ ok: true }))
        """, env=dict(AWT_DIR=os.path.join(self.tmp, "nowhere")))
        self.assertTrue(res["ok"])

    def child_side(self, prompt):
        return self.drive("""
            await on.session_start({}, { sessionManager: { getBranch: () => [] } })
            await on.before_agent_start({ prompt: %s, systemPromptOptions: { sections: {} } })
            console.log(JSON.stringify({ dir: process.env.AWT_DIR || null, by: process.env.AWT_BY || null, model: process.env.AWT_MODEL || null }))
        """ % json.dumps(prompt), env=dict(AWT_DIR=self.task, PI_SUBAGENT_CHILD="1", AWT_BY="parent", AWT_MODEL="parent-model"))

    def test_cl8_child_side_switches_env(self):
        self.child("pi-1")
        res = self.child_side(brief("pi-1"))
        self.assertEqual((res["dir"], res["by"]), (self.cpath("pi-1"), "sub:pi-1"))
        self.assertEqual(res["model"], "parent-model")

    def test_cl10_model_line(self):
        self.child("pi-1")
        res = self.child_side("RUN_KEY: pi-1\nMODEL: amazon-bedrock/m1\nDo it.\n")
        self.assertEqual((res["dir"], res["model"]), (self.cpath("pi-1"), "amazon-bedrock/m1"))
        res = self.child_side("RUN_KEY: pi-1\nDo it.\n")
        self.assertEqual(res["model"], "parent-model")
        self.assertEqual(self.child_side("RUN_KEY: pi-1\nMODEL: us.anthropic.claude-sonnet-4-5@x:0[1m]\n")["model"], "us.anthropic.claude-sonnet-4-5@x:0[1m]")
        for bad in ("m" * 201, "m1é", "m1;rm"):  # every row the child writes carries it: a model id, not brief text
            with self.subTest(model=bad[:20]):
                self.assertEqual(self.child_side("RUN_KEY: pi-1\nMODEL: %s\n" % bad)["model"], "parent-model")

    def test_cl8_child_side_never_follows_a_symlink(self):
        other = os.path.join(self.tmp, "other")
        os.mkdir(other)
        self.ok("init", "--goal", "g", "--done", "d", root=other)
        self.child("pi-1", other)
        os.symlink(self.cpath("pi-1", other), self.cpath("pi-1"))
        res = self.child_side(brief("pi-1"))
        self.assertEqual((res["dir"], res["by"]), (self.task, "parent"))

    def test_cl8_child_side_changes_nothing_otherwise(self):
        self.child("pi-1")
        self.mk("agent", "plain-1", self.task)
        for prompt in ("no key", "RUN_KEY: pi-9\n", brief("pi-1", 7), "RUN_KEY: Bad\n", "RUN_KEY: plain-1\n"):
            with self.subTest(prompt=prompt[:20]):
                res = self.child_side(prompt)
                self.assertEqual((res["dir"], res["by"], res["model"]), (self.task, "parent", "parent-model"))

    def test_cl8_child_side_needs_the_child_env(self):
        self.child("pi-1")
        res = self.drive("""
            await on.before_agent_start({ prompt: %s, systemPromptOptions: { sections: {} } })
            console.log(JSON.stringify({ dir: process.env.AWT_DIR || null }))
        """ % json.dumps(brief("pi-1")), env=dict(AWT_DIR=self.task))
        self.assertEqual(res["dir"], self.task)


# ---------- the store: child_runs recipe (L4, L5) ----------
PROMPT1 = "Scan for TODOs.\nRUN_KEY: scan-1\nDone when listed.\n"
PROMPT2 = "Check docs.\nRUN_KEY: scan-2\nDone when listed.\n"
RECIPE = os.path.join(ROOT, "docs", "recipes", "child-runs.sql")


class StoreRecipe(Prov):
    """A Claude parent session with two Agent calls (one linked by a ref, one by its RUN_KEY line only), their subagent transcripts, and a Paseo agent that joins the session to the parent node."""

    def setUp(self):
        super().setUp()
        self.tree()
        self.put_paseo()
        self.parent = self.agent_node("a-cc", "paseo:agent/agt_cc1")
        a1 = tool_use(1, "toolu_A1", "Agent", {"description": "d", "prompt": PROMPT1, "subagent_type": "general"})
        a2 = tool_use(3, "toolu_A2", "Task", {"description": "d", "prompt": PROMPT2})
        r1 = result(2, "toolu_A1", "done one")
        r1["toolUseResult"] = {"status": "completed", "agentId": "aaa111"}
        r2 = result(4, "toolu_A2", "done two")
        r2["toolUseResult"] = {"status": "completed", "agentId": "bbb222"}
        self.put([rec("user", 0, "go"), a1, r1, a2, r2, rec("assistant", 5, "all done")])

        def sub(t):
            return [dict(rec("user", 0, t), sessionId=SID), dict(rec("assistant", 1, "ok"), sessionId=SID)]
        self.put(sub("Scan for TODOs."), path=self.src(sub="agent-aaa111"))
        self.put(sub("Check docs."), path=self.src(sub="agent-bbb222"))
        self.ok("init", "--child", "scan-1", root=self.parent)
        self.ok("init", "--child", "scan-2", root=self.parent)
        self.ok("ref", "tool-call:toolu_A1", "--title", "scan-1", root=os.path.join(self.parent, "agents", "scan-1"))
        self.recipe = None
        if os.path.exists(RECIPE):
            with open(RECIPE, encoding="utf-8") as g:
                self.recipe = g.read()

    def build(self, *extra):
        self.run_src("all", *extra, root=self.root)

    def rows(self):
        self.assertIsNotNone(self.recipe, "docs/recipes/child-runs.sql is missing")
        c = sqlite3.connect("file:%s?mode=ro" % self.db, uri=True)
        try:
            cur = c.execute(self.recipe)
            cols = [d[0] for d in cur.description]
            return cols, sorted(cur.fetchall(), key=lambda r: (r[1], r[2]))
        finally:
            c.close()

    def test_st1_both_links_show(self):
        self.build()
        cols, rows = self.rows()
        self.assertEqual(cols, ["node_id", "run_key", "tool_call_id", "session_id", "tool_name", "link", "child_session_id"])
        self.assertEqual([(r[1], r[2], r[3], r[4], r[5]) for r in rows], [("scan-1", "toolu_A1", SID, "Agent", "ref"), ("scan-2", "toolu_A2", SID, "Task", "run_key")])
        want = {"path:" + os.path.relpath(os.path.join(self.parent, "agents", k), self.root) for k in ("scan-1", "scan-2")}
        self.assertEqual({r[0] for r in rows}, want)
        # the Paseo session joins to the parent node: one join shows the RUN_KEY of every row it launched
        got = self.q("select s.node_id, c.run_key from sessions s join (%s) c on c.session_id = s.session_id order by c.run_key" % self.recipe.rstrip().rstrip(";"))
        self.assertEqual(got, [("paseo:agent/agt_cc1", "scan-1"), ("paseo:agent/agt_cc1", "scan-2")])

    def test_st1_a_ref_and_a_run_key_do_not_double(self):
        self.ok("ref", "tool-call:toolu_A2", "--title", "scan-2", root=os.path.join(self.parent, "agents", "scan-2"))
        self.build()
        _, rows = self.rows()
        self.assertEqual([(r[1], r[2], r[5]) for r in rows], [("scan-1", "toolu_A1", "ref"), ("scan-2", "toolu_A2", "ref")])

    def test_st2_child_session_and_unchanged_joins(self):
        self.build()
        _, rows = self.rows()
        self.assertEqual([(r[1], r[6]) for r in rows], [("scan-1", SID + ".agent-aaa111"), ("scan-2", SID + ".agent-bbb222")])
        self.assertEqual(self.q("select session_id, node_id, join_confidence from sessions order by session_id"),
                         [(SID, "paseo:agent/agt_cc1", "session_id"), (SID + ".agent-aaa111", "paseo:agent/agt_cc1", "session_id"), (SID + ".agent-bbb222", "paseo:agent/agt_cc1", "session_id")])  # as before: a subagent file shares its parent's conversation id

    def test_st3_rebuild_is_byte_stable_and_incremental_equals_rebuild(self):
        self.build()
        self.assertEqual(self.q("select value from schema_meta where key='schema_version'"), [("7",)])
        a = self.digest()
        self.build("--rebuild")
        self.assertEqual(self.digest(), a)
        self.ok("ref", "tool-call:toolu_A2", "--title", "scan-2", root=os.path.join(self.parent, "agents", "scan-2"))
        self.build()
        inc = self.logical()
        self.build("--rebuild")
        self.assertEqual(self.logical(), inc)
        self.assertEqual(self.q("select value from schema_meta where key='schema_version'"), [("7",)])

    def test_st4_a_second_ingest_asks_for_no_rebuild(self):
        self.build()
        r = self.ok("ingest", "--source", "all", root=self.root)
        self.assertNotIn("rebuild", r.stdout + r.stderr)
        self.assertEqual(len(self.rows()[1]), 2)

    def test_l4_the_child_marker_is_in_the_node_record(self):
        self.build()
        got = self.q("select json_extract(fields, '$.run') from records where type='node' and json_extract(fields, '$.run') is not null order by 1")
        self.assertEqual(got, [("scan-1",), ("scan-2",)])
        self.assertEqual(self.q("select json_extract(fields, '$.target'), json_extract(fields, '$.title') from records where type='ref' and json_extract(fields, '$.kind')='tool-call'"),
                         [("tool-call:toolu_A1", "scan-1")])


if __name__ == "__main__":
    unittest.main()
