"""migrate-paseo (SPEC.md, "migrate-paseo"). End to end: the real script and the real awt in a temp HOME."""
import fcntl, hashlib, json, os, re, shutil, subprocess, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.realpath(os.path.join(HERE, ".."))
MIG = os.path.join(REPO, "migrate-paseo")
AWT = os.path.join(REPO, "awt")
FIX = os.path.join(REPO, "fixtures", "paseo-v0")
AKIA = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
TOKEN = "gh" + "p_" + "a1B2" * 9
HOME = os.path.join(FIX, "home")


def write_json(p, d):
    with open(p, "w") as g:
        json.dump(d, g)


def write_text(p, t):
    with open(p, "w") as g:
        g.write(t)


def read_text(p):
    with open(p, encoding="utf-8") as g:
        return g.read()


def read_json(p):
    with open(p) as g:
        return json.load(g)


def tree_hash(root, skip=()):
    h = hashlib.sha256()
    for dp, dns, fns in os.walk(root):
        dns.sort()
        for n in sorted(dns + fns):
            p = os.path.join(dp, n)
            rel = os.path.relpath(p, root)
            if rel in skip:
                continue
            h.update(rel.encode("utf-8", "surrogateescape") + b"\0")
            if os.path.isfile(p) and not os.path.islink(p):
                with open(p, "rb") as g:
                    data = g.read()
                if p.endswith("events.jsonl"):
                    data = re.sub(rb'"ts":"[^"]*"', b'"ts":""', data)
                h.update(hashlib.sha256(data).digest())
    return h.hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="migp-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "root")
        self.env = dict(os.environ, HOME=self.tmp, GIT_CONFIG_GLOBAL="/dev/null")
        self.env.pop("AWT_DIR", None)

    def mig(self, *args, env=None, snap=None, home=None):
        cmd = [sys.executable, MIG, self.root] + list(args)
        if home:
            cmd += ["--home", home]
        if snap:
            cmd += ["--from", os.path.join(FIX, snap + ".json") if not os.path.isabs(snap) else snap]
        return subprocess.run(cmd, capture_output=True, text=True, env=env or self.env, cwd=self.tmp)

    def ok(self, *args, **kw):
        r = self.mig(*args, **kw)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        return r

    def awt(self, *args, node=None):
        r = subprocess.run([sys.executable, "-I", AWT, "--dir", node or self.root] + list(args), capture_output=True, text=True, env=self.env, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def nodes(self):
        rows = json.loads(self.awt("list", "nodes", "--all", "--json"))
        return {r["path"]: (r["kind"], r["key"], r["status"]) for r in rows}

    def report(self):
        with open(os.path.join(self.root, "legacy", "paseo-migration.md"), encoding="utf-8") as g:
            return g.read()


BASIC = {
    "workspaces/parsekit-main": ("workspace", "paseo:workspace/wks_1", "active"),
    "workspaces/parsekit-main/tasks/imported": ("task", "paseo:task/wks_1/imported", "active"),
    "workspaces/parsekit-main/tasks/imported/agents/plan-the-parser-rewrite": ("agent", "paseo:agent/agt_1", "active"),
    "workspaces/parsekit-main/tasks/imported/agents/review-the-plan": ("agent", "paseo:agent/agt_2", "active"),
    "workspaces/parsekit-retry-bug": ("workspace", "paseo:workspace/wks_2", "active"),
    "workspaces/parsekit-retry-bug/tasks/imported": ("task", "paseo:task/wks_2/imported", "active"),
    "workspaces/parsekit-retry-bug/tasks/imported/agents/fix-retry-storm": ("agent", "paseo:agent/agt_3", "active"),
    "workspaces/parsekit-retry-bug/tasks/imported/agents/fix-retry-storm/agents/explore-backoff": ("agent", "paseo:agent/agt_4", "active"),
    "workspaces/parsekit-retry-bug/tasks/imported/agents/fix-retry-storm/agents/explore-backoff/agents/read-the-rfc": ("agent", "paseo:agent/agt_5", "active"),
    "workspaces/docs-site-main": ("workspace", "paseo:workspace/wks_3", "active"),
    "workspaces/docs-site-main/tasks/imported": ("task", "paseo:task/wks_3/imported", "active"),
    "workspaces/docs-site-main/tasks/imported/agents/draft-changelog": ("agent", "paseo:agent/agt_6", "done"),
}


class Basic(Base):
    def test_m1_m2_basic_tree(self):
        self.ok(snap="basic")
        self.assertEqual(self.nodes(), BASIC)
        keys = [v[1] for v in self.nodes().values()]
        self.assertEqual(len(keys), len(set(keys)))
        for i in range(1, 7):
            self.assertIn("paseo:agent/agt_%d" % i, keys)

    def test_refs_and_goals(self):
        self.ok(snap="basic")
        ws = os.path.join(self.root, "workspaces", "parsekit-main")
        refs = json.loads(self.awt("list", "refs", "--json", node=ws))
        targets = {r["target"] for r in refs}
        self.assertEqual(targets, {"/tmp/parsekit", "paseo:project/prj_1", "paseo:workspace/wks_1"})
        agent = os.path.join(ws, "tasks", "imported", "agents", "review-the-plan")
        r = json.loads(self.awt("resume", "--json", node=agent))
        self.assertEqual(r["goal"], "Review the plan")
        self.assertEqual([x["target"] for x in json.loads(self.awt("list", "refs", "--json", node=agent))], ["paseo:agent/agt_2"])
        self.assertEqual([x["kind"] for x in r["lineage"]], ["root", "workspace", "task"])

    def test_m5_dry_run_writes_nothing(self):
        r = self.ok("--dry-run", snap="basic")
        self.assertFalse(os.path.exists(self.root))
        self.assertIn("paseo:agent/agt_5", r.stdout)
        self.ok(snap="basic")
        before = tree_hash(self.root)
        self.ok("--dry-run", snap="basic")
        self.assertEqual(tree_hash(self.root), before)

    def test_m6_second_run_changes_nothing(self):
        self.ok(snap="basic")
        skip = (os.path.join("legacy", "paseo-migration.md"),)  # the report differs: created vs already present
        first = tree_hash(self.root, skip)
        self.ok(snap="basic")
        self.assertEqual(tree_hash(self.root, skip), first)

    def test_m6_moving_snapshot(self):
        self.ok(snap="basic")
        snap = read_json(os.path.join(FIX, "basic.json"))
        snap["agents"].append(dict(id="agt_7", name="Brand new", provider="claude", model="m", cwd="/tmp/parsekit", workspaceId="wks_1", parentAgentId=None, archived=False, background=False))
        snap["agents"][0]["archived"] = True
        snap["agents"][1]["name"] = "Renamed upstream"
        p = os.path.join(self.tmp, "snap2.json")
        write_json(p, snap)
        self.ok(snap=p)
        n = self.nodes()
        self.assertEqual(len(n), len(BASIC) + 1)
        self.assertEqual(n["workspaces/parsekit-main/tasks/imported/agents/plan-the-parser-rewrite"][2], "done")
        self.assertIn("workspaces/parsekit-main/tasks/imported/agents/review-the-plan", n)  # never renamed
        self.assertIn("workspaces/parsekit-main/tasks/imported/agents/brand-new", n)
        snap["agents"][0]["archived"] = False
        write_json(p, snap)
        self.ok(snap=p)
        self.assertEqual(self.nodes()["workspaces/parsekit-main/tasks/imported/agents/plan-the-parser-rewrite"][2], "done")  # awt owns the status after import

    def test_m8_no_timeline_text(self):
        snap = read_json(os.path.join(FIX, "basic.json"))
        for a in snap["agents"]:
            a["lastMessage"] = "TIMELINE-MARKER-ZZZ"
            a["timeline"] = [{"text": "TIMELINE-MARKER-ZZZ"}]
        p = os.path.join(self.tmp, "snap.json")
        write_json(p, snap)
        self.ok(snap=p)
        for dp, dns, fns in os.walk(self.root):
            for n in fns:
                with open(os.path.join(dp, n), "rb") as g:
                    self.assertNotIn(b"TIMELINE-MARKER-ZZZ", g.read(), os.path.join(dp, n))

    def test_nonempty_foreign_root_is_refused(self):
        os.makedirs(self.root)
        with open(os.path.join(self.root, "precious.txt"), "w") as g:
            g.write("x")
        r = self.mig(snap="basic")
        self.assertEqual(r.returncode, 1)
        self.assertIn("fix:", r.stderr)
        self.assertEqual(os.listdir(self.root), ["precious.txt"])

    def test_unreadable_snapshot(self):
        p = os.path.join(self.tmp, "bad.json")
        write_text(p, "{nope")
        r = self.mig(snap=p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("fix:", r.stderr)
        self.assertNotIn("Traceback", r.stderr)


class Shapes(Base):
    def test_m3_ambiguous(self):
        self.ok(snap="ambiguous")
        n = self.nodes()
        un = [p for p in n if p.count("/") == 1 and n[p][1].startswith("paseo:unassigned/")]
        self.assertEqual(len(un), 2)  # shared cwd, and /tmp/elsewhere
        self.assertEqual(sorted(un), ["workspaces/unassigned-elsewhere", "workspaces/unassigned-parsekit"])
        rep = self.report()
        self.assertIn("agt_1", rep)
        self.assertIn("agt_3", rep)
        self.assertIn("cwd matches 2 workspaces", rep)
        exact = [p for p, v in n.items() if v[1] == "paseo:agent/agt_2"][0]
        self.assertTrue(exact.startswith("workspaces/parsekit-second/"))

    def test_m4_background_skipped_and_listed(self):
        self.ok(snap="ambiguous")
        self.assertNotIn("paseo:agent/agt_4", [v[1] for v in self.nodes().values()])
        self.assertRegex(self.report(), r"agent agt_4.*background")

    def test_orphans(self):
        self.ok(snap="orphans")
        n = self.nodes()
        base = "workspaces/parsekit-main/tasks/imported/agents/"
        for name in ("lost-child", "cycle-a", "cycle-a/agents/cycle-b", "child-of-background"):
            self.assertIn(base + name.replace("cycle-a/", "cycle-a/"), n)
        rep = self.report()
        for needle in ("agt_missing", "parent cycle", "agt_5"):
            self.assertIn(needle, rep)

    def test_m9_hostile_snapshot(self):
        snap = read_json(os.path.join(FIX, "hostile.json"))
        snap["agents"][0]["name"] = snap["agents"][0]["name"].replace("SECRET-GOES-HERE", AKIA)
        p = os.path.join(self.tmp, "hostile.json")
        write_json(p, snap)
        r = self.ok(snap=p)
        n = self.nodes()
        keys = [v[1] for v in n.values()]
        self.assertIn("paseo:agent/../evil", keys)  # only a key, never a path
        self.assertEqual(keys.count("paseo:agent/agt_1"), 1)
        self.assertEqual(len(set(keys)), len(keys))
        self.assertIn("workspaces/parsekit-no-agents", n)
        for p in n:
            for part in p.split("/"):
                self.assertRegex(part, r"^[a-z0-9-]+$")
        for dp, dns, fns in os.walk(self.root):
            for f in fns:
                with open(os.path.join(dp, f), "rb") as g:
                    self.assertNotIn(AKIA.encode(), g.read(), os.path.join(dp, f))
        rep = self.report()
        self.assertIn("agt_1", rep.split("## Fields with a redacted secret")[1].split("##")[0])
        self.assertIn("duplicate id", rep)
        self.assertIn("missing or unusable id", rep)
        self.assertNotIn("\x1b", rep)

    def test_m7_report_and_exit_invariant(self):
        self.ok(snap="ambiguous")
        rep = self.report()
        self.assertIn("Created: ", rep)
        for head in ("## Skipped", "## Ambiguous", "## Orphans", "## Failed"):
            self.assertIn(head, rep)
        # a source the script cannot place at all must not exit 0
        snap = {"projects": [], "workspaces": [], "agents": [{"id": "agt_1", "name": "x", "cwd": "/tmp/x", "workspaceId": None}]}
        p = os.path.join(self.tmp, "s.json")
        write_json(p, snap)
        self.assertEqual(self.mig(snap=p).returncode, 0)  # lands under an unassigned workspace, which is an import


    def test_exit_1_when_an_item_is_neither_imported_nor_listed(self):
        self.ok(snap="basic")  # make the root, then take away the right to add to it
        ws = os.path.join(self.root, "workspaces")
        snap = read_json(os.path.join(FIX, "basic.json"))
        snap["workspaces"].append(dict(id="wks_9", projectId="prj_1", project="parsekit", name="late", cwd="/tmp/parsekit", archived=False))
        p = os.path.join(self.tmp, "late.json")
        write_json(p, snap)
        os.chmod(ws, 0o555)
        self.addCleanup(os.chmod, ws, 0o755)
        if os.access(ws, os.W_OK):
            self.skipTest("directory permissions are not enforced (root)")
        r = self.mig(snap=p)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("wks_9", self.report().split("## Failed")[1])
        self.assertNotIn("Traceback", r.stderr)

    def test_archived_workspace_with_an_active_child_is_noted_not_forced(self):
        self.ok(snap="basic")
        task = os.path.join(self.root, "workspaces", "parsekit-main", "tasks", "imported")
        self.awt("ask", "who owns the lexer?", node=task)  # the task cannot be finished while this is open
        snap = read_json(os.path.join(FIX, "basic.json"))
        snap["workspaces"][0]["archived"] = True
        p = os.path.join(self.tmp, "arch.json")
        write_json(p, snap)
        self.ok(snap=p)
        n = self.nodes()
        self.assertEqual(n["workspaces/parsekit-main"][2], "active")
        self.assertEqual(n["workspaces/parsekit-main/tasks/imported"][2], "active")
        notes = self.report().split("## Notes")[1].split("##")[0]
        self.assertRegex(notes, r"workspace wks_1 could not be marked done")

    def test_a_second_run_while_one_holds_the_lock_exits_1_with_a_fix(self):  # C22
        self.ok(snap="basic")
        fd = os.open(os.path.join(self.root, "legacy", "paseo-migration.md"), os.O_WRONLY)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        r = self.mig(snap="basic")
        self.assertEqual(r.returncode, 1)
        self.assertIn("another migrate-paseo is running", r.stderr)
        self.assertIn("fix:", r.stderr)


class HomeSource(Base):
    def copy_home(self):
        h = tempfile.mkdtemp(dir=self.tmp) + "/h"
        shutil.copytree(HOME, h)
        return h

    def test_m10_home_route_equals_snapshot_route(self):
        self.ok(home=HOME)
        self.assertEqual(self.nodes(), BASIC)
        self.assertIn("(none)", self.report().split("## Ambiguous")[1].split("##")[0])  # exact workspace ids: nothing to guess

    def test_default_home_is_dot_paseo(self):
        shutil.copytree(HOME, os.path.join(self.tmp, ".paseo"))
        self.ok()
        self.assertEqual(self.nodes(), BASIC)

    def test_workspaces_sharing_a_cwd_are_exact(self):
        h = self.copy_home()
        p = os.path.join(h, "projects", "workspaces.json")
        ws = read_json(p)
        ws[1]["cwd"] = ws[0]["cwd"]  # several local workspaces on one checkout
        write_json(p, ws)
        self.ok(home=h)
        n = self.nodes()
        self.assertEqual({k: v for k, v in n.items() if v[0] == "agent"}, {k: v for k, v in BASIC.items() if v[0] == "agent"})
        self.assertFalse([p for p in n if "unassigned" in p])

    def test_background_and_archived(self):
        h = self.copy_home()
        p = os.path.join(h, "projects", "workspaces.json")
        ws = read_json(p)
        ws[2]["archivedAt"] = "2026-01-03T00:00:00.000Z"
        ws[1]["background"] = True
        write_json(p, ws)
        f = os.path.join(h, "agents", "tmp-parsekit", "agt_2.json")
        a = read_json(f)
        a["internal"] = True
        write_json(f, a)
        self.ok(home=h)
        n = self.nodes()
        self.assertEqual(n["workspaces/docs-site-main"][2], "done")
        self.assertNotIn("paseo:workspace/wks_2", [v[1] for v in n.values()])
        self.assertNotIn("paseo:agent/agt_2", [v[1] for v in n.values()])
        rep = self.report()
        self.assertRegex(rep, r"workspace wks_2.*background")
        self.assertRegex(rep, r"agent agt_2.*background")

    def test_hostile_home_is_a_clean_refusal_or_skip(self):
        h = self.copy_home()
        write_text(os.path.join(h, "agents", "tmp-parsekit", "agt_1.json"), "{nope")
        write_text(os.path.join(h, "agents", "tmp-parsekit", "agt_2.json"), "[" * 100000)
        write_json(os.path.join(h, "agents", "tmp-parsekit", "agt_x.json"), ["not", "an", "object"])
        self.ok(home=h)
        self.assertIn("unreadable", self.report())
        for bad in ({}, "x", [1, None, "s", {"workspaceId": 5, "cwd": ["a"]}]):
            h2 = self.copy_home()
            write_json(os.path.join(h2, "projects", "workspaces.json"), bad)
            self.root = os.path.join(self.tmp, "root-%d" % len(json.dumps(bad)))
            r = self.mig(home=h2)
            self.assertNotIn("Traceback", r.stderr)
            if r.returncode:
                self.assertIn("fix:", r.stderr)

    def test_missing_home_is_a_clean_refusal(self):
        r = self.mig(home=os.path.join(self.tmp, "nope"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("fix:", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertFalse(os.path.exists(self.root))


class Secrets(Base):
    def snapshot(self):
        return {"projects": [dict(id="prj_1", name="proj " + TOKEN, path="/tmp/parsekit")],
                "workspaces": [dict(id="wks_1", projectId="prj_1", project="proj " + TOKEN, name="ws " + TOKEN, cwd="/tmp/" + TOKEN, archived=False),
                               dict(id="wks_2", projectId="prj_1", project="parsekit", name="plain", cwd="/tmp/parsekit", archived=False)],
                "agents": [dict(id="agt_1", name="title " + TOKEN, provider="p" + TOKEN, model="m" + TOKEN, cwd="/tmp/" + TOKEN, workspaceId="wks_1", parentAgentId=None, archived=False, background=False),
                           dict(id="agt_2", name="child", provider="claude", model="m", cwd="/tmp/x", workspaceId="wks_missing" + TOKEN, parentAgentId="agt_1", archived=False, background=False),
                           dict(id="agt_3", name="lost\n## injected", provider="claude", model="m", cwd="/tmp/y", workspaceId="wks_gone" + TOKEN + "\n## injected heading", parentAgentId=None, archived=False, background=False),
                           dict(id="agt_" + TOKEN, name="secret id", provider="claude", model="m", cwd="/tmp/y", workspaceId="wks_2", parentAgentId=None, archived=False, background=False),
                           dict(id="agt_4", name="in plain", provider="claude", model="m", cwd="/tmp/parsekit", workspaceId="wks_2", parentAgentId=None, archived=False, background=False)]}

    def assert_clean(self, *outs):
        for o in outs:
            self.assertNotIn(TOKEN, o)
        for dp, dns, fns in os.walk(self.root):
            for f in fns:
                with open(os.path.join(dp, f), "rb") as g:
                    self.assertNotIn(TOKEN.encode(), g.read(), os.path.join(dp, f))

    def test_no_secret_reaches_files_or_output(self):
        p = os.path.join(self.tmp, "s.json")
        write_json(p, self.snapshot())
        d = self.mig("--dry-run", snap=p)
        self.assertEqual(d.returncode, 0, d.stderr)
        self.assertNotIn(TOKEN, d.stdout + d.stderr)
        r = self.ok(snap=p)
        self.assert_clean(r.stdout, r.stderr)
        n = self.nodes()
        keys = [v[1] for v in n.values()]
        for k in ("paseo:workspace/wks_1", "paseo:agent/agt_1", "paseo:agent/agt_2", "paseo:agent/agt_3", "paseo:agent/agt_4"):
            self.assertIn(k, keys)  # one secret never drops a workspace or an agent
        rep = self.report()
        self.assertEqual(rep.count("\n## "), 6)  # no heading injected through a newline
        red = rep.split("## Fields with a redacted secret")[1].split("\n## ")[0]
        for f in ("workspace wks_1: name", "workspace wks_1: cwd", "agent agt_1: title", "agent agt_1: provider", "agent agt_1: model"):
            self.assertIn(f, red)
        self.assertIn("id matches the secret scan", rep)
        r = self.ok(snap=p)  # rerun: same
        self.assert_clean(r.stdout, r.stderr)

    def test_failed_awt_call_does_not_echo_argv(self):
        # a title only awt refuses (a secret shape the migrator does not know) must not be echoed back
        snap = self.snapshot()
        snap["workspaces"][0]["name"] = "ok"
        write_json(os.path.join(self.tmp, "t.json"), snap)
        r = self.ok(snap=os.path.join(self.tmp, "t.json"))
        self.assertNotIn(TOKEN, r.stdout + r.stderr + self.report())


class Reruns(Base):
    def test_user_status_survives_a_rerun(self):
        self.ok(snap="basic")
        node = os.path.join(self.root, "workspaces", "parsekit-main", "tasks", "imported", "agents", "plan-the-parser-rewrite")
        self.awt("status", "done", node=node)
        self.ok(snap="basic")
        self.assertEqual(self.nodes()["workspaces/parsekit-main/tasks/imported/agents/plan-the-parser-rewrite"][2], "done")

    def test_counts_created_and_present(self):
        r = self.ok(snap="basic")
        self.assertIn("created 3 workspaces, 6 agents", r.stdout)
        r = self.ok(snap="basic")
        self.assertIn("created 0 workspaces, 0 agents (already present: 3, 6)", r.stdout)
        self.assertIn("Created: 0 workspaces, 0 tasks, 0 agents", self.report())

    def test_subagents_are_not_resolved_to_a_workspace(self):
        snap = read_json(os.path.join(FIX, "basic.json"))
        snap["agents"][3]["workspaceId"] = "wks_gone"  # agt_4 has a parent
        snap["agents"][3]["cwd"] = "/tmp/nowhere"
        p = os.path.join(self.tmp, "s.json")
        write_json(p, snap)
        self.ok(snap=p)
        self.assertEqual(self.nodes(), BASIC)
        self.assertIn("(none)", self.report().split("## Ambiguous")[1].split("##")[0])

    def test_cwd_is_normalised(self):
        snap = read_json(os.path.join(FIX, "basic.json"))
        snap["agents"][0].update(workspaceId=None, cwd="/tmp/parsekit/")
        p = os.path.join(self.tmp, "s.json")
        write_json(p, snap)
        self.ok(snap=p)
        self.assertEqual(self.nodes(), BASIC)

    def test_dash_i_works(self):
        r = subprocess.run([sys.executable, "-I", MIG, self.root, "--dry-run", "--from", os.path.join(FIX, "basic.json")], capture_output=True, text=True, env=self.env, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_killed_run_does_not_leave_a_current_looking_report(self):
        snap = {"projects": [], "workspaces": [dict(id="wks_1", name="main", project="parsekit", cwd="/tmp/parsekit")],
                "agents": [dict(id="agt_%d" % i, name="agent %d" % i, cwd="/tmp/parsekit", workspaceId="wks_1") for i in range(400)]}
        p = os.path.join(self.tmp, "big.json")
        write_json(p, snap)
        self.ok(snap="basic")  # leaves a finished report behind
        rep = os.path.join(self.root, "legacy", "paseo-migration.md")
        pr = subprocess.Popen([sys.executable, MIG, self.root, "--from", p], env=self.env, cwd=self.tmp, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(200):
                time.sleep(0.1)
                if pr.poll() is not None:
                    self.skipTest("finished before it could be killed")
                if "Run in progress" in read_text(rep):
                    break
            pr.kill()
        finally:
            pr.wait()
        self.assertIn("interrupted", read_text(rep))


if __name__ == "__main__":
    unittest.main()
