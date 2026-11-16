"""awt ui (SPEC.md, "ui"): Datasette over store.db, read-only, on 127.0.0.1, with the docs/recipes queries canned. Fictional data."""
import glob, json, os, shutil, signal, socket, subprocess, sys, time, unittest, urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_ingest import rec
from test_recipes import QUESTIONS, recipes
from test_store import Store


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class UI(Store):
    def meta(self, *a):
        r = self.ok("ui", "--print-metadata", *a, root="")
        return json.loads(r.stdout)

    def test_metadata_has_one_canned_query_per_recipe(self):
        self.build()
        m = self.meta()
        qs = m["databases"]["store"]["queries"]
        self.assertEqual(len(qs), QUESTIONS)
        q = qs["l5_unjoined_sessions"]
        self.assertIn("SELECT session_id", q["sql"])
        self.assertTrue(q["title"].startswith("Which sessions are not joined"))
        self.assertNotIn("parquet", " ".join(qs))
        stub = qs["l7_redecisions"]
        self.assertIn("needs data", stub["title"].lower())
        self.assertIn("needs data", stub["description"].lower())
        part = qs["l8_latency_percentiles"]
        self.assertIn("partial", part["title"].lower())
        self.assertNotIn("permissions", m)  # no write permission is granted

    def test_no_store_is_refused_with_the_fix(self):
        r = self.bad("ui", root="")
        self.assertIn("ingest", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_datasette_missing_is_refused_with_the_install_command(self):
        self.build()
        self.env["AWT_DATASETTE"] = os.path.join(self.tmp, "no-such-datasette")
        r = self.bad("ui", root="")
        self.assertIn("datasette", r.stderr)
        self.assertRegex(r.stderr, r"pipx install datasette|uv tool install datasette")
        self.assertNotIn("Traceback", r.stderr)

    @unittest.skipUnless(shutil.which("datasette"), "datasette is not installed")
    def test_serves_read_only_on_loopback_and_stops(self):
        self.build()
        port = free_port()
        before = open(self.db, "rb").read()
        p = subprocess.Popen([sys.executable, "-I", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "awt"), "ui", "--port", str(port)],
                             env=self.env, cwd=self.tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        self.addCleanup(lambda: os.killpg(p.pid, signal.SIGKILL) if p.poll() is None else None)
        base = "http://127.0.0.1:%d" % port
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/", timeout=2).read()
                break
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(0.2)
        else:
            self.fail("datasette did not come up")
        # a canned query runs, with blank parameters
        d = json.load(urllib.request.urlopen(base + "/store/l5_unjoined_sessions.json?_shape=array", timeout=10))
        self.assertEqual([x["session_id"] for x in d], ["3f0c1a2b-0000-4000-8000-00000000aaaa"])
        d = json.load(urllib.request.urlopen(base + "/store/l1_projects_inactive_30d.json?_shape=array&now=&_size=5", timeout=10))
        self.assertIsInstance(d, list)
        # writing is refused
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/store.json?sql=delete+from+sessions&_shape=array", timeout=10)
        # it listens on loopback only
        ps = subprocess.run(["ps", "-o", "args=", "-p", str(p.pid)], capture_output=True, text=True).stdout
        ch = subprocess.run(["pgrep", "-P", str(p.pid), "-fl", "datasette"], capture_output=True, text=True).stdout
        self.assertIn("127.0.0.1", ps + ch)
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=15)
        self.assertEqual(open(self.db, "rb").read(), before)
        self.assertEqual(subprocess.run(["pgrep", "-f", "serve.*%d" % port], capture_output=True, text=True).stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
