"""Review fixes for PR #24 (M3 half-initialised root, L4 gen_docs --check and resume --hook, L5 stale brief temp files). Temp dirs only."""
import os, shutil, subprocess, sys, tempfile, time, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_migrate_paseo import BASIC, AWT, REPO, Base


class TestHalfInitRoot(Base):
    def test_migrate_finishes_a_root_whose_first_init_was_killed(self):
        os.makedirs(os.path.join(self.root, ".awt"))
        self.ok(snap="basic")
        self.assertEqual(self.nodes(), BASIC)


class TestStaleBriefTemp(Base):
    def run_awt(self, *a):
        r = subprocess.run([sys.executable, "-I", AWT, "--dir", self.root] + list(a), capture_output=True, text=True, env=self.env, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def test_old_temp_goes_young_stays_and_gitignore_lists_it(self):
        self.run_awt("init", "--kind", "root")
        self.assertIn(".awt/*.tmp", open(os.path.join(self.root, ".gitignore")).read().splitlines())
        old, young = [os.path.join(self.root, ".awt", "BRIEF.%d.tmp" % n) for n in (1, 2)]
        for p in (old, young):
            open(p, "w").close()
        t = time.time() - 120
        os.utime(old, (t, t))
        self.run_awt("note", "kept going")
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(young))


class TestDocsTools(unittest.TestCase):
    def test_check_flags_a_stale_reference_page(self):
        d = tempfile.mkdtemp()
        try:
            for sub in ("tools", "docs"):
                shutil.copytree(os.path.join(REPO, sub), os.path.join(d, sub))
            shutil.copy2(AWT, d)
            run = lambda: subprocess.run([sys.executable, os.path.join(d, "tools", "gen_docs.py"), "--check"], capture_output=True, text=True)
            self.assertEqual(run().returncode, 0, run().stderr)
            open(os.path.join(d, "docs", "reference", "gone.md"), "w").close()
            r = run()
            self.assertEqual(r.returncode, 1)
            self.assertIn("docs/reference/gone.md", r.stderr)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_resume_hook_survives_a_flag_without_help(self):
        d = tempfile.mkdtemp()
        try:
            src = open(AWT, encoding="utf-8").read()
            self.assertIn('h[1].get(fl[0], "")', src)
            src = src.replace('"--json": "machine-readable output"}),\n    "list"', '}),\n    "list"', 1)
            p = os.path.join(d, "awt")
            open(p, "w", encoding="utf-8").write(src)
            r = subprocess.run([sys.executable, p, "resume", "--hook"], capture_output=True, text=True, cwd=d, env={k: v for k, v in os.environ.items() if k != "AWT_DIR"})
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
