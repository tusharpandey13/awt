"""awt ui (SPEC.md, "ui"): Datasette over store.db, read-only, on 127.0.0.1, with the docs/recipes queries canned. Fictional data."""
import glob, http.client, json, os, shutil, signal, socket, sqlite3, subprocess, sys, time, unittest, urllib.error, urllib.request

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
        self.assertIn("partial", stub["title"].lower())  # no recipe is a stub any more
        self.assertIn("needs", stub["description"].lower())
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
        self.assertRegex(r.stderr, r"pipx install 'datasette<1'|uv tool install 'datasette<1'")
        self.assertNotIn("Traceback", r.stderr)

    def fake_datasette(self, version):
        """A datasette that prints its version and records how it was started."""
        p = os.path.join(self.tmp, "fake-datasette")
        with open(p, "w") as g:
            g.write("#!/bin/sh\nif [ \"$1\" = --version ]; then echo 'datasette, version %s'; exit 0; fi\necho \"$@\" > '%s'\n" % (version, os.path.join(self.tmp, "args.txt")))
        os.chmod(p, 0o755)
        self.env["AWT_DATASETTE"] = p

    def test_datasette_1x_is_refused_because_it_would_drop_the_recipes_silently(self):
        self.build()
        self.fake_datasette("1.0a19")
        r = self.bad("ui", root="")
        self.assertIn("1.x", r.stderr)
        self.assertRegex(r.stderr, r"fix: .*datasette<1")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "args.txt")))

    def test_datasette_0x_is_started_on_the_live_store_without_a_copy(self):
        self.build()
        self.fake_datasette("0.65.1")
        r = self.ok("ui", root="")
        args = open(os.path.join(self.tmp, "args.txt")).read().split()
        self.assertEqual(args[:2], ["serve", self.db])
        self.assertNotIn("-i", args)
        self.assertEqual(args[args.index("-h") + 1], "127.0.0.1")
        self.assertIn("live", r.stdout)

    def test_an_old_store_is_refused_with_the_rebuild_command(self):
        self.build()
        c = sqlite3.connect(self.db)
        c.execute("UPDATE schema_meta SET value='5' WHERE key='schema_version'")
        c.commit()
        c.close()
        self.fake_datasette("0.65.1")
        r = self.bad("ui", root="")
        self.assertIn("store schema 5 < 7", r.stderr)
        self.assertRegex(r.stderr, r"fix: awt ingest --rebuild")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "args.txt")))

    def start(self, port):
        p = subprocess.Popen([sys.executable, "-I", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "awt"), "ui", "--port", str(port)],
                             env=self.env, cwd=self.tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        self.addCleanup(lambda: os.killpg(p.pid, signal.SIGKILL) if p.poll() is None else None)
        return p, None

    def wait_up(self, port):
        for _ in range(100):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=2).read()
                return
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(0.2)
        self.fail("datasette did not come up")

    def get(self, port, path, host=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.putrequest("GET", path, skip_host=True)
        c.putheader("Host", host or "127.0.0.1:%d" % port)
        c.endheaders()
        r = c.getresponse()
        r.read()
        c.close()
        return r.status

    @unittest.skipUnless(shutil.which("datasette"), "datasette is not installed")
    def test_serves_read_only_on_loopback_and_stops(self):
        self.build()
        port = free_port()
        before = open(self.db, "rb").read()
        p, _ = self.start(port)
        base = "http://127.0.0.1:%d" % port
        self.wait_up(port)
        # a canned query runs, with blank parameters
        d = json.load(urllib.request.urlopen(base + "/store/l5_unjoined_sessions.json?_shape=array", timeout=10))
        self.assertEqual([x["session_id"] for x in d], ["3f0c1a2b-0000-4000-8000-00000000aaaa"])
        d = json.load(urllib.request.urlopen(base + "/store/l1_projects_inactive_30d.json?_shape=array&now=&_size=5", timeout=10))
        self.assertIsInstance(d, list)
        # writing is refused
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/store.json?sql=delete+from+sessions&_shape=array", timeout=10)
        # it listens on loopback only and serves the live file, read-only and not immutable: no copy of the store is made
        ps = subprocess.run(["ps", "-o", "args=", "-p", str(p.pid)], capture_output=True, text=True).stdout
        ch = subprocess.run(["pgrep", "-P", str(p.pid), "-fl", "datasette"], capture_output=True, text=True).stdout
        self.assertIn("127.0.0.1", ps + ch)
        self.assertIn(self.db, ch)
        self.assertNotIn(" -i ", ch)
        self.assertNotIn("immutable", ch)
        tmpdir = [x for x in ch.split() if "awt-ui-" in x][0].rsplit("/metadata.json", 1)[0]
        self.assertTrue(os.path.isdir(tmpdir))
        self.assertFalse(os.path.exists(os.path.join(tmpdir, "store.db")))
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=15)
        self.assertEqual(open(self.db, "rb").read(), before)
        self.assertFalse(os.path.exists(tmpdir))
        self.assertEqual(subprocess.run(["pgrep", "-f", "serve.*%d" % port], capture_output=True, text=True).stdout.strip(), "")

    @unittest.skipUnless(shutil.which("datasette"), "datasette is not installed")
    def test_no_database_download_and_only_loopback_host_names(self):
        self.build()
        port = free_port()
        self.start(port)
        self.wait_up(port)
        self.assertEqual(self.get(port, "/"), 200)
        self.assertEqual(self.get(port, "/", host="localhost:%d" % port), 200)
        self.assertEqual(self.get(port, "/", host="evil.example"), 400)
        self.assertEqual(self.get(port, "/store.json?sql=select+1&_shape=array", host="attacker.example:%d" % port), 400)
        self.assertIn(self.get(port, "/store.db"), (400, 403))
        self.assertIn(self.get(port, "/store.db", host="localhost"), (400, 403))

    @unittest.skipUnless(shutil.which("datasette"), "datasette is not installed")
    def test_a_later_ingest_shows_on_the_next_query_and_the_page_never_tears(self):
        self.build()
        port = free_port()
        self.start(port)
        self.wait_up(port)
        n = lambda: json.load(urllib.request.urlopen("http://127.0.0.1:%d/store.json?sql=select+count(*)+as+n+from+messages&_shape=array" % port, timeout=10))[0]["n"]
        before = n()
        self.put(self.rows_() + [rec("user", 6, "one more"), rec("assistant", 7, "ok")])
        self.ok("ingest", "--source", "claude", root=self.root)
        self.assertGreater(n(), before)  # the live file, opened read-only: a committed ingest is visible without a restart

    @unittest.skipUnless(shutil.which("datasette"), "datasette is not installed")
    def test_a_taken_port_gets_a_free_one_and_the_printed_url_works(self):
        self.build()
        busy = socket.socket()
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        self.addCleanup(busy.close)
        p, _ = self.start(busy.getsockname()[1])
        lines = [p.stdout.readline(), p.stdout.readline()]
        url = [x for x in lines if "http://" in x][0]
        port = int(url.split("127.0.0.1:")[1].split("/")[0])
        self.assertNotEqual(port, busy.getsockname()[1])
        self.assertIn("taken", "".join(lines))
        self.wait_up(port)
        self.assertNotIn("metadata", "".join(lines))

    @unittest.skipUnless(shutil.which("datasette"), "datasette is not installed")
    def test_sighup_stops_the_server_and_removes_its_temp_dir(self):
        self.build()
        port = free_port()
        p, _ = self.start(port)
        self.wait_up(port)
        ch = subprocess.run(["pgrep", "-P", str(p.pid), "-fl", "datasette"], capture_output=True, text=True).stdout
        tmpdir = [x for x in ch.split() if "awt-ui-" in x][0].rsplit("/metadata.json", 1)[0]
        p.send_signal(signal.SIGHUP)
        p.wait(timeout=15)
        self.assertFalse(os.path.exists(tmpdir))
        self.assertEqual(subprocess.run(["pgrep", "-f", "serve.*%d" % port], capture_output=True, text=True).stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
