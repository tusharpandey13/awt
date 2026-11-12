import hashlib, json, os, re, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.realpath(os.path.join(HERE, ".."))
MIG = os.path.join(REPO, "migrate-wt")
FIX = os.path.join(REPO, "fixtures", "wt-v0", "tasks", "sample-task")
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e.x", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e.x",
           GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")


def tree_hash(root):
    h = hashlib.sha256()
    for dp, dns, fns in os.walk(root):
        dns.sort()
        for n in sorted(dns + fns):
            p = os.path.join(dp, n)
            h.update(os.path.relpath(p, root).encode("utf-8", "surrogateescape") + b"\0")
            if os.path.islink(p):
                h.update(b"L" + os.readlink(p).encode("utf-8", "surrogateescape"))
            elif os.path.isfile(p):
                with open(p, "rb") as g:
                    h.update(hashlib.sha256(g.read()).digest())
    return h.hexdigest()


def skipped_list(report_path):
    out, on = [], False
    with open(report_path, encoding="utf-8") as g:
        for ln in g:
            if ln.startswith("## "):
                on = ln.strip() == "## Skipped"
            elif on and ln.startswith("- `"):
                out.append(ln[3:ln.index("`", 3)])
    return out


def unaccounted(old, new, skipped):
    """Generic: every regular file under old is in new (by content hash) or under a skipped path."""
    have = set()
    for dp, _, fns in os.walk(new):
        for f in fns:
            p = os.path.join(dp, f)
            if os.path.isfile(p) and not os.path.islink(p):
                with open(p, "rb") as g:
                    have.add(hashlib.sha256(g.read()).hexdigest())
    bad = []
    for dp, _, fns in os.walk(old):
        for f in fns:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, old)
            if os.path.islink(p) or any(rel == s or rel.startswith(s + os.sep) for s in skipped):
                continue
            with open(p, "rb") as g:
                if hashlib.sha256(g.read()).hexdigest() not in have:
                    bad.append(rel)
    return bad


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="mig-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.old = os.path.join(self.tmp, "old")
        self.new = os.path.join(self.tmp, "new")

    def mig(self, *a, code=0):
        r = subprocess.run([sys.executable, MIG] + list(a), capture_output=True, text=True, env=ENV, cwd=self.tmp)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r

    def run_new(self, *a, root=None):
        return subprocess.run([sys.executable, "-I", os.path.join(root or self.new, "awt")] + list(a), capture_output=True,
                              text=True, env=ENV, cwd=root or self.new)

    def fixture(self, dst=None):
        dst = dst or self.old
        shutil.copytree(FIX, dst)
        os.symlink(os.path.join(self.tmp, "nope"), os.path.join(dst, "refs-dangling"))
        os.makedirs(os.path.join(dst, "refs"))
        os.symlink(os.path.join(self.tmp, "nope"), os.path.join(dst, "refs", "gone"))
        os.symlink(self.tmp, os.path.join(dst, "refs", "live"))
        os.symlink("/etc/hosts", os.path.join(dst, "outside-link"))
        with open(os.path.join(dst, "context", "café notes ü.md"), "w", encoding="utf-8") as g:
            g.write("unicode name\n")
        with open(os.path.join(dst, "artifacts", "blob.bin"), "wb") as g:
            g.write(bytes(range(256)) * 4)
        return dst

    def rows(self, typ, root=None):
        with open(os.path.join(root or self.new, ".awt", "events.jsonl"), encoding="utf-8") as g:
            rs = [json.loads(x) for x in g if x.startswith("{")]
        return [r for r in rs if r["type"] == typ]

    def report(self, root=None):
        with open(os.path.join(root or self.new, "legacy", "MIGRATION.md"), encoding="utf-8") as g:
            return g.read()

    def test_single_task_full(self):
        self.fixture()
        h = tree_hash(self.old)
        r = self.mig(self.old, self.new)
        self.assertEqual(h, tree_hash(self.old))
        rep = self.report()
        self.assertEqual(unaccounted(self.old, self.new, skipped_list(os.path.join(self.new, "legacy", "MIGRATION.md"))), [])
        self.assertIn("tmp/node_modules", skipped_list(os.path.join(self.new, "legacy", "MIGRATION.md")))
        targets = [x["target"] for x in self.rows("ref")]
        for t in ("context/slack-kickoff.md", "context/slack-followup.md", "context/design-page.md", "https://example.com/design",
                  "parsekit/parsekit-core", "https://example.com/thread/1", self.tmp):
            self.assertIn(t, targets)
        self.assertEqual(len(targets), len(set(targets)))
        self.assertEqual(sorted(x["why"].split("]")[0] for x in self.rows("decision")),
                         ["[legacy D1", "[legacy D2", "[legacy D3", "[legacy D4 dup", "[legacy D4 dup", "[legacy D6"])
        self.assertIn("duplicate heading D4", rep)
        self.assertIn("D6 overturns D3 in prose only", rep)
        self.assertIn("malformed JSON", rep)
        self.assertIn("not in ascending order", rep)
        self.assertIn("refs/gone", rep)
        self.assertIn("outside-link", rep)
        self.assertIn("/etc/hosts", rep)
        st = self.rows("state")[0]
        self.assertIn("lexer rewrite", st["now"])
        self.assertTrue(self.rows("task")[0]["goal"].startswith("Parsekit needs"))
        self.assertTrue(os.path.isfile(os.path.join(self.new, "legacy", "AGENTS.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.new, "docs", "TASK.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.new, "context", "café notes ü.md")))
        self.assertEqual(open(os.path.join(self.new, "docs", "blob.bin"), "rb").read(), bytes(range(256)) * 4)
        self.assertTrue(os.path.isfile(os.path.join(self.new, "misc", "old-scratch", "scratch-notes.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.new, "misc", "old-scratch", "node_modules")))
        self.assertFalse([x for x in os.listdir(self.tmp) if "migrating" in x])
        d = self.run_new("doctor")
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        self.assertIn("0 quarantined", d.stdout)
        rs = self.run_new("resume")
        self.assertEqual(rs.returncode, 0, rs.stdout + rs.stderr)

    def test_supersede_links_and_status(self):
        self.fixture()
        with open(os.path.join(self.old, "decisions.md"), "a") as g:
            g.write("\n## D7: Restore cache\n2030-01-07 · supersedes: D6\nChoice: restore\nWhy: because\n")
        p = os.path.join(self.old, "task.yml")
        s = open(p).read().replace("status: active", "status: archived")
        open(p, "w").write(s)
        self.mig(self.old, self.new)
        ds = self.rows("decision")
        self.assertEqual([d.get("supersedes") is not None for d in ds].count(True), 1)
        self.assertEqual(self.rows("status")[-1]["status"], "done")

    def test_refuses_nonempty_and_dry_run(self):
        self.fixture()
        os.makedirs(self.new)
        open(os.path.join(self.new, "x"), "w").close()
        self.mig(self.old, self.new, code=1)
        os.remove(os.path.join(self.new, "x"))
        h = tree_hash(self.old)
        r = self.mig(self.old, self.new, "--dry-run")
        self.assertIn("copy", r.stdout)
        self.assertEqual(os.listdir(self.new), [])
        shutil.rmtree(self.new)
        self.mig(self.old, self.new, "--dry-run")
        self.assertFalse(os.path.exists(self.new))
        self.assertEqual(h, tree_hash(self.old))
        self.mig(self.old, self.new)  # empty NEW allowed
        self.mig(self.old, self.new, code=1)

    def test_secret_row_refused_reported_file_flagged(self):
        self.fixture()
        fake = "AKIA" + "ABCDEFGHIJKLMNOP"
        with open(os.path.join(self.old, "decisions.md"), "a") as g:
            g.write("\n## D8: Use key\n2030-01-08 · supersedes: none\nChoice: use %s\nWhy: because\n" % fake)
        with open(os.path.join(self.old, "context", "creds.txt"), "w") as g:
            g.write("key=%s\n" % fake)
        self.mig(self.old, self.new)
        rep = self.report()
        self.assertIn("awt refused `decision D8`", rep)
        self.assertIn("secret-shaped", rep)
        self.assertIn("context/creds.txt", rep)
        self.assertNotIn(fake, rep)
        self.assertTrue(os.path.isfile(os.path.join(self.new, "context", "creds.txt")))
        self.assertEqual(self.run_new("doctor").returncode, 0)

    def test_over_cap_cut_with_pointer(self):
        self.fixture()
        with open(os.path.join(self.old, "decisions.md"), "a") as g:
            g.write("\n## D9: Long\n2030-01-09 · supersedes: none\nChoice: %s\nWhy: %s\n" % ("x " * 400, "y " * 400))
        self.mig(self.old, self.new)
        d = [x for x in self.rows("decision") if x["why"].startswith("[legacy D9")][0]
        self.assertLessEqual(len(d["choice"]), 300)
        self.assertIn("[legacy/decisions.md D9]", d["choice"])

    def test_nested_git_repo_is_skipped_and_ref(self):
        self.fixture()
        sub = os.path.join(self.old, "vendor repo")
        os.makedirs(sub)
        open(os.path.join(sub, "code.py"), "w").write("print(1)\n")
        subprocess.run(["git", "init", "-q", sub], env=ENV, check=True)
        h = tree_hash(self.old)
        self.mig(self.old, self.new)
        self.assertEqual(h, tree_hash(self.old))
        sk = skipped_list(os.path.join(self.new, "legacy", "MIGRATION.md"))
        self.assertIn("vendor repo", sk)
        self.assertIn(sub, [x["target"] for x in self.rows("ref")])
        self.assertEqual(unaccounted(self.old, self.new, sk), [])
        self.assertFalse(os.path.exists(os.path.join(self.new, "misc", "vendor repo")))

    def test_tracker_layout(self):
        os.makedirs(os.path.join(self.old, "tasks"))
        self.fixture(os.path.join(self.old, "tasks", "alpha"))
        os.makedirs(os.path.join(self.old, "tasks", "beta"))
        open(os.path.join(self.old, "tasks", "beta", "TASK.md"), "w").write("Just beta.\n")
        open(os.path.join(self.old, "notes.txt"), "w").write("tracker level\n")
        h = tree_hash(self.old)
        self.mig(self.old, self.new)
        self.assertEqual(h, tree_hash(self.old))
        for t in ("alpha", "beta"):
            root = os.path.join(self.new, t)
            sk = skipped_list(os.path.join(root, "legacy", "MIGRATION.md"))
            self.assertEqual(unaccounted(os.path.join(self.old, "tasks", t), root, sk), [])
            d = self.run_new("doctor", root=root)
            self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
            self.assertIn("0 quarantined", d.stdout)
        self.assertIn("notes.txt", skipped_list(os.path.join(self.new, "MIGRATION.md")))
        self.assertEqual(self.rows("task", os.path.join(self.new, "beta"))[0]["goal"], "Just beta.")

    def test_real_tree_copy(self):
        src = os.path.join(REPO, "..")
        roots = {os.path.realpath(r) for r in ("/", "/tmp", tempfile.gettempdir(), os.path.expanduser("~"))}
        if os.path.realpath(src) in roots:
            self.skipTest("checkout's parent is a temp/system/home root, not a workspace; copying it is unbounded")
        cp = os.path.join(self.tmp, "wtcopy")
        shutil.copytree(src, cp, symlinks=True, ignore=shutil.ignore_patterns("__pycache__"))
        h = tree_hash(cp)
        self.mig(cp, self.new)
        self.assertEqual(h, tree_hash(cp))
        sk = skipped_list(os.path.join(self.new, "legacy", "MIGRATION.md"))
        self.assertEqual(unaccounted(cp, self.new, sk), [])
        self.assertIn(os.path.basename(os.path.realpath(REPO)), sk)


if __name__ == "__main__":
    unittest.main()
