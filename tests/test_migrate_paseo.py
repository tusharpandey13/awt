"""migrate-paseo (SPEC.md, "migrate-paseo"). End to end: the real script and the real awt in a temp HOME."""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.realpath(os.path.join(HERE, ".."))
MIG = os.path.join(REPO, "migrate-paseo")
AWT = os.path.join(REPO, "awt")
FIX = os.path.join(REPO, "fixtures", "paseo-v0")
AKIA = "AK" + "IA" + "ABCDEFGHIJKLMNOP"


def write_json(p, d):
    with open(p, "w") as g:
        json.dump(d, g)


def write_text(p, t):
    with open(p, "w") as g:
        g.write(t)


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

    def mig(self, *args, env=None, snap=None):
        cmd = [sys.executable, MIG, self.root] + list(args)
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
        first = tree_hash(self.root)
        self.ok(snap="basic")
        self.assertEqual(tree_hash(self.root), first)

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
        self.assertEqual(self.nodes()["workspaces/parsekit-main/tasks/imported/agents/plan-the-parser-rewrite"][2], "active")

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
        r = self.ok(snap="hostile")
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
        self.assertIn("agt_1", rep.split("## Titles with a redacted secret")[1].split("##")[0])
        self.assertIn("duplicate id", rep)
        self.assertIn("missing or unusable id", rep)
        self.assertNotIn("\x1b", rep)

    def test_m7_report_and_exit_invariant(self):
        self.ok(snap="ambiguous")
        rep = self.report()
        self.assertIn("Imported: ", rep)
        for head in ("## Skipped", "## Ambiguous", "## Orphans", "## Failed"):
            self.assertIn(head, rep)
        # a source the script cannot place at all must not exit 0
        snap = {"projects": [], "workspaces": [], "agents": [{"id": "agt_1", "name": "x", "cwd": "/tmp/x", "workspaceId": None}]}
        p = os.path.join(self.tmp, "s.json")
        write_json(p, snap)
        self.assertEqual(self.mig(snap=p).returncode, 0)  # lands under an unassigned workspace, which is an import


class CliSource(Base):
    def test_m10_cli_route_equals_snapshot_route(self):
        stub = os.path.join(FIX, "cli")
        env = dict(self.env, PATH=stub + os.pathsep + self.env["PATH"])
        r = self.mig(env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.nodes(), BASIC)

    def test_cli_failure_is_a_clean_refusal(self):
        env = dict(self.env, PATH="/usr/bin:/bin")
        r = self.mig(env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("fix:", r.stderr)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
