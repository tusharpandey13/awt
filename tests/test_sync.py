"""Two hosts (SPEC.md, Two hosts): ledger order, sync lock, awt-sync, remotes, store after a pull, profiles. T-HS1-T-HS44 of tests/TEST-SPEC.md.
Temp dirs, a local bare git repo and a local http.server only: no real remote, no network, no GitHub."""
import datetime, http.server, importlib.machinery, importlib.util, itertools, json, os, random, re, shutil, sqlite3, stat, subprocess, sys, tempfile, threading, time, unittest, fcntl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synchelp as H
from test_awt import AWT, Base, slurp
from test_ingest import GH, rec
from test_store import tool_use

HAVE_GIT = H.have_git()
_n = itertools.count()
TS = "2030-01-01T10:%02d:%02d.%06dZ"  # after every row a test makes with the wall clock


def mod(root=None, path=AWT):
    """awt as a module, with ROOT set: for reading rows through load()."""
    loader = importlib.machinery.SourceFileLoader("awtmod%d" % next(_n), path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    m = importlib.util.module_from_spec(spec)
    saved = sys.path[:]
    loader.exec_module(m)
    sys.path[:] = saved  # awt trims sys.path for itself
    m.ROOT = root
    m.SYNC = False  # no sync lock held by the test process
    return m


def ts(sec, us=0, minute=0):
    return TS % (minute, sec, us)


def row(t, host, typ, **f):
    d = dict(v=2, ts=t, type=typ, host=host, by="agent", model="m")
    d.update(f)
    return json.dumps(d, separators=(",", ":")).encode()


def old_awt(tmp):
    """v0.4.1's awt from git history, or None."""
    r = subprocess.run(["git", "-C", H.WT, "show", "v0.4.1:awt"], capture_output=True)
    if r.returncode:
        return None
    p = os.path.join(tmp, "awt-0.4.1")
    with open(p, "wb") as g:
        g.write(r.stdout)
    os.chmod(p, 0o755)
    return p


AGE = re.compile(r"(\d+[mhd] ago|just now)")


class One(Base):
    """One standalone task with hand-made ledgers."""

    def setUp(self):
        super().setUp()
        self.init()
        self.env["AWT_HOST"] = "host-a"

    def ledger(self):
        return self.p(".awt", "events.jsonl")

    def append(self, *lines):
        with open(self.ledger(), "ab") as g:
            for ln in lines:
                g.write(ln if ln.endswith(b"\n") else ln + b"\n")

    def D(self):
        m = mod(self.root)
        return m.load()

    def quarantined(self):
        return int(re.search(r"(\d+) quarantined rows", self.awt("doctor").stdout).group(1))

    def doctor(self):
        return self.awt("doctor").stdout


class TestOrder(One):
    def test_hs1_v2_rows_and_ts_shape(self):  # T-HS1: HS1
        self.ok("note", "hello")
        last = json.loads(self.events_raw()[-1])
        self.assertEqual(last["v"], 2)
        self.assertRegex(last["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$")
        self.assertEqual(self.quarantined(), 0)
        bad = json.loads(self.events_raw()[-1])
        bad["ts"] = "2026-11-22T10:00:00Z"
        bad["id"] = "n-00000001"
        self.append(json.dumps(bad).encode())
        self.assertEqual(self.quarantined(), 1)
        bad.update(v=1, id="n-00000002")
        self.append(json.dumps(bad).encode())
        self.assertEqual(self.quarantined(), 1)  # the same row as v1 is legacy and reads

    def events_raw(self):
        with open(self.ledger(), "rb") as g:
            return [x for x in g.read().split(b"\n") if x.strip()]

    def test_hs2_old_awt_reads_v2(self):  # T-HS2: HS1, fact "valid() accepts any v"
        old = old_awt(self.tmp)
        if not old:
            self.skipTest("no v0.4.1 tag in this clone")
        self.ok("note", "from the new awt")
        self.ok("state", "--now", "n", "--next", "x")
        r = subprocess.run([sys.executable, "-I", old, "--dir", self.root, "doctor"], capture_output=True, text=True, env=self.env)
        self.assertIn("0 quarantined rows", r.stdout)
        r = subprocess.run([sys.executable, "-I", old, "--dir", self.root, "list", "notes"], capture_output=True, text=True, env=self.env)
        self.assertIn("from the new awt", r.stdout)

    def test_hs3_monotonic_ts(self):  # T-HS3: HS2
        self.ok("note", "one")
        first = json.loads(self.events_raw()[-1])["ts"]
        env = dict(self.env, AWT_TEST_CLOCK_SKEW_S="-3600")
        self.ok("note", "two", env=env)
        second = json.loads(self.events_raw()[-1])["ts"]
        f = lambda t: datetime.datetime.strptime(t, "%Y-%m-%dT%H:%M:%S.%fZ")
        self.assertEqual(f(second) - f(first), datetime.timedelta(microseconds=1))
        env = dict(self.env, AWT_TEST_CLOCK_SKEW_S="3600")
        self.ok("note", "three", env=env)
        third = json.loads(self.events_raw()[-1])["ts"]
        self.assertGreater(f(third) - f(second), datetime.timedelta(minutes=50))

    def test_hs4_effect_begin_ts_under_lock(self):  # T-HS4: HS2
        self.write("outbox/m.md", "hi\n")
        r = self.ok("effect", "plan", "--target", "slack:#eng")
        eid = re.search(r"(e-[0-9a-f]{8})", r.stdout).group(1)
        procs = [subprocess.Popen([sys.executable, "-I", AWT, "--dir", self.root, "effect", "begin", eid], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env) for _ in range(20)]
        codes = [p.wait() for p in procs]
        for p in procs:
            p.stdout.close()
            p.stderr.close()
        self.assertEqual(codes.count(0), 1)
        D = self.D()
        self.assertEqual(D["eff"][eid]["state"], "begun")
        self.assertEqual(D["bad"], 0)
        v2 = [json.loads(x)["ts"] for x in self.events_raw() if json.loads(x).get("v") == 2]
        self.assertEqual(v2, sorted(v2))
        self.assertEqual(len(set(v2)), len(v2))

    def test_hs5_duplicates_read_once(self):  # T-HS5: HS3
        for i in range(50):
            self.ok("note", "n%d" % i)
        before = self.D()
        lines = self.events_raw()
        with open(self.ledger(), "wb") as g:
            for ln in lines:
                g.write((ln + b"\n") * (2 if b'"type":"note"' in ln else 1))
        after = self.D()
        self.assertEqual(after["rows"], before["rows"])
        self.assertEqual((after["dups"], after["bad"]), (50, 0))

    def two_host_rows(self):
        a, b = "host-a", "host-b"
        return [row(ts(1), a, "state", now="a1", next="x"), row(ts(2), b, "state", now="b1", next="x"), row(ts(3), a, "task", goal="G-a", done_means="d"),
                row(ts(4), b, "task", goal="G-b", done_means="d"), row(ts(5), a, "status", status="paused"), row(ts(6), b, "status", status="active"),
                row(ts(7), a, "ref", target="http://x/1", title="t1", kind="link", access="ok"), row(ts(8), b, "ref", target="http://x/1", title="t2", kind="link", access="ok"),
                row(ts(9), a, "question", id="q-00000001", text="why?"), row(ts(10), a, "answer", ref="q-00000001", text="because a"), row(ts(11), b, "answer", ref="q-00000001", text="because b"),
                row(ts(12), a, "effect", id="e-00000001", step="planned", attempt=1, target="t", key="k1"), row(ts(13), a, "effect", id="e-00000001", step="begun", attempt=1),
                row(ts(14), b, "effect", id="e-00000001", step="sent", attempt=1), row(ts(15), a, "note", id="n-00000001", text="na"), row(ts(15), b, "note", id="n-00000002", text="nb")]

    def test_hs6_order_is_a_function_of_the_set(self):  # T-HS6: HS4
        rows = self.two_host_rows()
        legacy = open(self.ledger(), "rb").read()
        rng = random.Random(6)
        seen = None
        briefs = []
        for i in range(100):
            rng.shuffle(rows)
            with open(self.ledger(), "wb") as g:
                g.write(legacy + b"\n".join(rows) + b"\n")
            D = self.D()
            snap = json.dumps([D["rows"], D["task"], D["status"], D["states"], D["refs"], D["ans"], {k: v["state"] for k, v in D["eff"].items()}], sort_keys=True)
            self.assertEqual(snap, seen or snap, "shuffle %d" % i)
            seen = snap
            if i < 5:
                briefs.append(AGE.sub("AGE", self.ok("resume").stdout))
        self.assertEqual(len(set(briefs)), 1)
        D = self.D()
        self.assertEqual((D["task"]["goal"], D["status"], D["states"]["main"]["now"], D["refs"]["http://x/1"]["title"], D["ans"]["q-00000001"]["text"], D["eff"]["e-00000001"]["state"]),
                         ("G-b", "active", "b1", "t2", "because a", "sent"))

    def test_hs7_tie_break(self):  # T-HS7: HS4
        legacy = open(self.ledger(), "rb").read()
        r1, r2, r3 = (row(ts(1), "host-b", "note", id="n-0000000b", text="b"), row(ts(1), "host-a", "note", id="n-0000000a", text="a"),
                      row(ts(1), "host-a", "note", id="n-00000009", text="a0"))
        with open(self.ledger(), "wb") as g:
            g.write(legacy + b"\n".join([r1, r2, r3]) + b"\n")
        notes = [n["id"] for n in self.D()["notes"]]
        self.assertEqual(notes, ["n-00000009", "n-0000000a", "n-0000000b"])  # host, then bytes

    def make_legacy(self, awt_old):
        """A task built with v0.4.1 awt: notes, states, a decision, a question, an effect, a ref, a capture, a child node."""
        e = dict(self.env)

        def o(*a, **kw):
            r = subprocess.run([sys.executable, "-I", awt_old, "--dir", self.root] + list(a), capture_output=True, text=True, env=e, **kw)
            self.assertEqual(r.returncode, 0, "%s\n%s%s" % (a, r.stdout, r.stderr))
            return r
        o("note", "legacy note")
        o("state", "--now", "legacy now", "--next", "legacy next")
        d = re.search(r"(d-[0-9a-f]{8})", o("decide", "keep v1", "--why", "old").stdout).group(1)
        o("decide", "newer", "--why", "r", "--supersedes", d)
        q = re.search(r"(q-[0-9a-f]{8})", o("ask", "which?").stdout).group(1)
        o("answer", q, "this one")
        o("ref", "https://example.com/doc", "--title", "Doc")
        self.write("outbox/b.md", "body\n")
        eid = re.search(r"(e-[0-9a-f]{8})", o("effect", "plan", "--target", "slack:#eng", "--body", "outbox/b.md").stdout).group(1)
        o("effect", "begin", eid)
        o("effect", "mark", eid, "sent", "--ref", "https://example.com/s")
        o("capture", "--from", "slack", "--title", "thread", input="pasted text\n")

    def test_hs8_legacy_reads_as_before(self):  # T-HS8: HS5, IS6
        old = old_awt(self.tmp)
        if not old:
            self.skipTest("no v0.4.1 tag in this clone")
        shutil.rmtree(self.root)
        os.mkdir(self.root)
        subprocess.run([sys.executable, "-I", old, "--dir", self.root, "init", "--goal", "g", "--done", "d"], capture_output=True, env=self.env, check=True)
        self.make_legacy(old)
        digest = {p: open(p, "rb").read() for p in (self.ledger(),)}
        outs = {}
        for name, awt in (("old", old), ("new", AWT)):
            res = []
            for args in (["resume"], ["list", "notes", "--all", "--json"], ["list", "decisions", "--all", "--json"], ["list", "effects", "--all", "--json"], ["list", "state", "--all", "--json"], ["list", "--all"], ["resume", "--json"]):
                r = subprocess.run([sys.executable, "-I", awt, "--dir", self.root] + args, capture_output=True, text=True, env=self.env)
                res.append(AGE.sub("AGE", r.stdout))
            outs[name] = res
        self.assertEqual(outs["old"], outs["new"])
        self.assertEqual(digest[self.ledger()], open(self.ledger(), "rb").read())  # reading changed no byte
        self.assertEqual(self.D()["dups"], 0)
        self.assertEqual(self.D()["v1_late"], [])
        self.ok("note", "new row")
        self.assertEqual(json.loads(self.events_raw()[-1])["v"], 2)
        self.assertEqual([r.get("v") for r in self.D()["rows"]][-1], 2)

    def test_hs9_late_v1_rows(self):  # T-HS9: HS6
        self.ok("note", "v2 first")
        self.append(row(ts(1), "host-b", "note", id="n-0000aaaa", text="old awt").replace(b'"v":2', b'"v":1'))
        D = self.D()
        self.assertEqual(D["rows"][-1]["text"], "v2 first")  # the v1 row reads before every v2 row
        self.assertEqual(D["rows"][0]["text"], "old awt")
        n = len(self.events_raw())
        self.assertEqual(D["v1_late"], [n])
        self.assertRegex(self.doctor(), r"warn 1 v1 rows after v2 rows \(lines %d\): a host runs an older awt; install the same version on every host" % n)

    def test_hs10_host_name(self):  # T-HS10: HS7
        r = self.ok("note", "x", env=dict(self.env, AWT_HOST="box-1"))
        self.assertEqual(r.stderr, "")
        self.assertEqual(json.loads(self.events_raw()[-1])["host"], "box-1")
        r = self.ok("note", "y", env=dict(self.env, AWT_HOST="a b"))
        self.assertEqual(r.stderr.count("warn:"), 1)
        self.assertEqual(json.loads(self.events_raw()[-1])["host"], __import__("socket").gethostname())

    def test_hs11_concurrent_state_last_writer_wins(self):  # T-HS11: HS8
        self.append(row(ts(1), "host-a", "state", now="from a", next="n"), row(ts(2), "host-b", "state", now="from b", next="n"))
        self.assertIn("from b", self.ok("resume").stdout)
        self.assertEqual(self.ok("list", "state", "--all", "--json").stdout.count('"now"'), 2)

    def test_hs12_two_supersedes(self):  # T-HS12: HS8
        self.ok("decide", "base", "--why", "w")
        d = self.D()["rows"][-1]["id"]
        self.append(row(ts(1), "host-a", "decision", id="d-0000000a", choice="X", why="w", supersedes=d), row(ts(2), "host-b", "decision", id="d-0000000b", choice="Y", why="w", supersedes=d))
        D = self.D()
        self.assertEqual({x["id"] for x in D["cur_dec"]}, {"d-0000000a", "d-0000000b"})
        self.assertIn("warn decision %s superseded by two rows (d-0000000a@host-a, d-0000000b@host-b): supersede one of them" % d, self.doctor())

    def test_hs13_two_answers(self):  # T-HS13: HS8
        self.append(row(ts(1), "host-a", "question", id="q-00000001", text="why?"), row(ts(3), "host-b", "answer", ref="q-00000001", text="b"), row(ts(2), "host-a", "answer", ref="q-00000001", text="a"))
        self.assertEqual(self.D()["ans"]["q-00000001"]["text"], "a")
        self.assertIn("warn question q-00000001 answered twice (hosts host-a, host-b)", self.doctor())

    def test_hs14_effect_across_hosts(self):  # T-HS14: HS8
        self.append(row(ts(1), "host-a", "effect", id="e-00000001", step="planned", attempt=1, target="t", key="k"), row(ts(2), "host-a", "effect", id="e-00000001", step="begun", attempt=1),
                    row(ts(3), "host-b", "effect", id="e-00000001", step="sent", attempt=1))
        D = self.D()
        self.assertEqual((D["eff"]["e-00000001"]["state"], D["bad"]), ("sent", 0))
        self.append(row(ts(4), "host-a", "effect", id="e-00000002", step="planned", attempt=1, target="t2", key="k2"), row(ts(5), "host-a", "effect", id="e-00000002", step="begun", attempt=1),
                    row(ts(6), "host-b", "effect", id="e-00000002", step="begun", attempt=1))
        D = self.D()
        self.assertEqual((D["eff"]["e-00000002"]["state"], D["bad"]), ("begun", 1))
        self.assertIn("warn effect e-00000002: begun on host-a and host-b (attempt 1); check the target and mark it", self.doctor())

    def test_hs15_future_rows(self):  # T-HS15: HS9; resolves the [unverified] brief age of a future ts
        future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=600)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        self.append(row(future, "host-b", "state", now="from the future", next="n"))
        d = self.doctor()
        m = re.search(r"warn rows up to (\d+) s ahead of this clock \(host host-b\): check NTP on both hosts", d)
        self.assertTrue(m, d)
        self.assertTrue(595 <= int(m.group(1)) <= 605)
        brief = self.ok("resume").stdout
        self.assertIn("from the future", brief)
        self.assertNotRegex(brief, r"-\d+[smhd]")
        self.assertIn("just now", brief + self.ok("list", "state").stdout)  # a future ts reads as age 0


class Hold:
    """Hold LOCK_EX on a directory's fd, as a sync does."""

    def __init__(self, d):
        self.fd = os.open(d, os.O_RDONLY)
        fcntl.flock(self.fd, fcntl.LOCK_EX)

    def release(self):
        os.close(self.fd)
        self.fd = None


class TestLock(One):
    def test_hs16_writes_wait_hooks_do_not(self):  # T-HS16: HS10, HS11
        h = Hold(self.p(".awt"))
        try:
            env = dict(self.env, AWT_TEST_SYNC_WAIT_S="1")
            t0 = time.time()
            r = self.bad("note", "blocked", env=env)
            self.assertIn("a sync of %s is in progress" % self.root, r.stderr)
            self.assertIn("fix: rerun in a few seconds", r.stderr)
            self.assertGreaterEqual(time.time() - t0, 0.9)
            t0 = time.time()
            r = self.ok("resume", "--hook", env=dict(self.env, AWT_TEST_SYNC_WAIT_S="5"))
            self.assertLess(time.time() - t0, 2.5)
            t0 = time.time()
            r = self.ok("list", env=env)
            self.assertIn("is being synced; output may be partial", r.stderr)
        finally:
            h.release()
        t0 = time.time()
        self.ok("note", "after the release")
        self.assertLess(time.time() - t0, 2)
        self.assertEqual(self.D()["notes"][-1]["text"], "after the release")

    def test_hs16b_waiting_write_goes_through_after_release(self):  # E-HS12 step 2: a write waits for the release
        h = Hold(self.p(".awt"))
        threading.Timer(1.5, h.release).start()
        r = self.ok("note", "waited", env=dict(self.env, AWT_TEST_SYNC_WAIT_S="8"))
        self.assertEqual(self.D()["notes"][-1]["text"], "waited")

    def test_hs18_hook_write_is_dropped(self):  # T-HS18: HS11
        h = Hold(self.p(".awt"))
        try:
            t0 = time.time()
            payload = json.dumps({"hook_event_name": "PreToolUse", "session_id": "s", "cwd": self.tmp, "tool_name": "Bash", "tool_input": {"command": "git push origin a"}, "tool_use_id": "toolu_1"})
            r = self.awt("ingest", "--event", "--hook", input=payload, env=dict(self.env, AWT_TEST_SYNC_WAIT_S="5"))
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
            self.assertLess(time.time() - t0, 2.5)
        finally:
            h.release()
        self.assertEqual(self.D()["eff"], {})
        n = len(open(self.ledger(), "rb").read())
        self.assertEqual(n, len(open(self.ledger(), "rb").read()))
        self.assertNotIn(b"effect", open(self.ledger(), "rb").read())


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class Hosts(unittest.TestCase):
    def setUp(self):
        self.h = H.H2()
        self.addCleanup(self.h.cleanup)
        self.h.setup()

    def ok(self, r, msg=""):
        self.assertEqual(r.returncode, 0, "%s\n%s%s" % (msg, r.stdout, r.stderr))
        return r

    def write(self, h, text, rel=H.H2.TASK):
        return self.ok(self.h.awt(h, "note", text, dir=self.h.node(h, rel)))

    def doctor(self, h, *a):
        return self.h.awt(h, "doctor", *a)

    def test_hs19_awt_sync_sequence(self):  # T-HS19: HS12, HS14
        self.write("A", "from a")
        r = self.ok(self.h.sync("A"))
        self.assertRegex(r.stdout, r"^synced %s: committed 1 files, merged 0 commits, pushed\n$" % re.escape(self.h.tree("A")))
        self.write("B", "from b")
        r = self.ok(self.h.sync("B"))
        self.assertRegex(r.stdout, r"committed 1 files, merged 1 commits, pushed")
        self.ok(self.h.sync("A"))
        texts = lambda h: [n["text"] for n in mod(self.h.node(h, H.H2.TASK)).load()["notes"]]
        self.assertEqual((texts("A"), texts("B")), (["from a", "from b"], ["from a", "from b"]))
        self.assertEqual(H.check_is4(self.h.remote, self.h.T), [])
        r = self.ok(self.h.sync("B"))
        self.assertIn("committed 0 files, merged 0 commits, no push", r.stdout)

    def test_hs17_no_deadlock(self):  # T-HS17: HS10 lock order, effect begin (log lock, then sync lock) racing awt-sync (sync lock only)
        node = self.h.node("A", H.H2.TASK)
        for i in range(30):
            r = self.ok(self.h.awt("A", "effect", "plan", "--target", "slack:#r%d" % i, dir=node))
            eid = re.search(r"(e-[0-9a-f]{8})", r.stdout).group(1)
            ps = [subprocess.Popen([sys.executable, "-I", AWT, "--dir", node, "effect", "begin", eid], env=self.h.env("A"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True),
                  subprocess.Popen([sys.executable, "-I", H.SYNC, "--dir", self.h.tree("A")], env=self.h.env("A"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)]
            for p in ps:
                out, err = p.communicate(timeout=30)
                self.assertEqual(p.returncode, 0, "round %d: %s%s" % (i, out, err))
        D = mod(node).load()
        self.assertEqual((D["bad"], len([e for e in D["eff"].values() if e["state"] == "begun"])), (0, 30))

    def test_hs20_lock_busy_skips(self):  # T-HS20: HS14
        hold = Hold(os.path.join(self.h.tree("A"), ".awt"))
        try:
            r = self.h.sync("A", "--wait", "0.3")
            self.assertEqual(r.returncode, 0)
            self.assertIn("skipped", r.stderr)
            self.assertEqual(r.stdout, "")
        finally:
            hold.release()

    def test_hs21_heals_torn_tail(self):  # T-HS21: HS12 step 3
        self.write("A", "x")
        led = os.path.join(self.h.node("A", H.H2.TASK), ".awt", "events.jsonl")
        with open(led, "ab") as g:
            g.write(b'{"v":2,"ts":"2026')
        r = self.ok(self.h.sync("A"))
        self.assertEqual(H.check_is4(self.h.remote, self.h.T), [])
        self.assertTrue(open(led, "rb").read().endswith(b"\n"))
        self.assertIn("1 quarantined", self.h.awt("A", "doctor", dir=self.h.node("A", H.H2.TASK)).stdout)

    def test_hs22_rejected_push_never_forced(self):  # T-HS22: HS12 step 7, IS7
        fake = os.path.join(self.h.T, "fakebin")
        os.makedirs(fake)
        real = shutil.which("git")
        racer = self.h.tree("B")
        log = os.path.join(self.h.T, "argv.log")
        mark = os.path.join(self.h.T, "raced")
        with open(os.path.join(fake, "git"), "w") as g:
            g.write('#!/bin/sh\necho "$@" >> %s\nif [ "$3" = push ] || [ "$1" = push ] || echo "$@" | grep -q " push "; then\n  if [ ! -e %s ]; then touch %s\n    %s -C %s push -q origin HEAD:main\n  fi\nfi\nexec %s "$@"\n' % (log, mark, mark, real, racer, real))
        os.chmod(os.path.join(fake, "git"), 0o755)
        self.write("B", "b first")
        self.ok(self.h.git("B", "add", "-A"))
        self.ok(self.h.git("B", "commit", "-q", "-m", "b"))
        self.write("A", "a first")
        env = {"PATH": fake + os.pathsep + os.environ["PATH"]}
        r = self.ok(self.h.sync("A", over=env))
        self.assertIn("push rejected", r.stdout)
        r = self.ok(self.h.sync("A"))
        self.assertIn("pushed", r.stdout)
        self.ok(self.h.sync("B"))
        argv = open(log).read()
        self.assertNotRegex(argv, r"--force|--force-with-lease|reset --hard| -f |push \+")
        self.assertEqual(self.h.all_lines("A"), self.h.all_lines("B"))
        self.assertEqual(H.check_is4(self.h.remote, self.h.T), [])

    def test_hs23_ignored_files(self):  # T-HS23: HS15
        d = self.doctor("A").stdout
        self.assertNotIn("does not ignore", d)
        gi = os.path.join(self.h.tree("A"), ".gitignore")
        txt = open(gi).read().replace("BRIEF.md\n", "")
        open(gi, "w").write(txt)
        d = self.doctor("A").stdout
        self.assertRegex(d, r"warn git does not ignore BRIEF.md: add the line 'BRIEF.md' to ")

    def test_hs24_union_attribute(self):  # T-HS24: HS16
        ga = os.path.join(self.h.tree("A"), ".gitattributes")
        self.assertNotIn("merge", self.doctor("A").stdout.replace("merged", ""))
        open(ga, "w").write("# no union here\n")
        self.assertIn("warn events.jsonl is not merged as union: add the line 'events.jsonl merge=union' to", self.doctor("A").stdout)

    def test_hs25_hook_present(self):  # T-HS25: HS17
        hk = os.path.join(self.h.tree("A"), ".git", "hooks", "pre-commit")
        self.assertNotIn("pre-commit hook", self.doctor("A").stdout)
        os.chmod(hk, 0o644)
        self.assertIn("warn the pre-commit hook is missing, not executable", self.doctor("A").stdout)
        os.chmod(hk, 0o755)
        open(hk, "w").write("#!/bin/sh\nexit 0\n")
        self.assertIn("warn the pre-commit hook", self.doctor("A").stdout)
        alt = os.path.join(self.h.T, "hooks")
        os.makedirs(alt)
        open(os.path.join(alt, "pre-commit"), "w").write("#!/bin/sh\nawt doctor --staged\n")
        os.chmod(os.path.join(alt, "pre-commit"), 0o755)
        self.ok(self.h.git("A", "config", "core.hooksPath", alt))
        self.assertNotIn("pre-commit hook", self.doctor("A").stdout)
        os.unlink(hk)
        self.assertNotIn("pre-commit hook", self.doctor("A").stdout)  # core.hooksPath is honoured
        self.ok(self.h.git("A", "config", "--unset", "core.hooksPath"))
        self.assertIn("pre-commit hook", self.doctor("A").stdout)

    def staged(self, h="A"):
        return self.h.awt(h, "doctor", "--staged")

    def ledger_path(self, h="A"):
        return os.path.join(self.h.node(h, H.H2.TASK), ".awt", "events.jsonl")

    def test_hs26_torn_tail_refused(self):  # T-HS26: HS21
        with open(self.ledger_path(), "ab") as g:
            g.write(b'{"v":2,"ts":"2026-11')
        self.ok(self.h.git("A", "add", "-A"))
        r = self.staged()
        self.assertEqual(r.returncode, 1)
        self.assertIn("error: %s/.awt/events.jsonl: ledger does not end with a newline (torn tail)" % H.H2.TASK, r.stderr)
        self.assertIn("fix: run awt-sync, or printf", r.stderr)
        c = self.h.git("A", "commit", "-q", "-m", "x")
        self.assertNotEqual(c.returncode, 0)  # the installed hook refuses the commit

    def test_hs27_changed_or_removed_rows_refused(self):  # T-HS27: HS22
        led = self.ledger_path()
        orig = open(led, "rb").read()
        mid = orig.index(b'"goal"') + 9
        open(led, "wb").write(orig[:mid] + b"Z" + orig[mid + 1:])
        self.ok(self.h.git("A", "add", "-A"))
        r = self.staged()
        self.assertEqual(r.returncode, 1)
        self.assertIn("ledger rows were changed or removed since HEAD", r.stderr)
        self.assertIn("fix: git restore --staged", r.stderr)
        open(led, "wb").write(orig[:orig.rstrip(b"\n").rindex(b"\n") + 1])  # the last row removed
        self.ok(self.h.git("A", "add", "-A"))
        self.assertEqual(self.staged().returncode, 1)
        open(led, "wb").write(orig)
        self.ok(self.h.git("A", "add", "-A"))
        self.assertEqual(self.staged().returncode, 0)
        # a new file has no HEAD blob: no prefix check
        self.ok(self.h.awt("A", "init", "--kind", "task", "--name", "fresh", "--goal", "g", "--done", "d", dir=self.h.node("A", "projects/parsekit/workspaces/main")))
        self.ok(self.h.git("A", "add", "-A"))
        self.assertEqual(self.staged().returncode, 0)

    def test_hs28_conflict_markers(self):  # T-HS28: HS23
        with open(self.ledger_path(), "ab") as g:
            g.write(b"=======\n")
        self.ok(self.h.git("A", "add", "-A"))
        r = self.staged()
        self.assertEqual(r.returncode, 1)
        self.assertIn("conflict markers", r.stderr)
        self.assertIn("merge=union", r.stderr)

    def test_hs29_unreadable_rows_only_warn(self):  # T-HS29: HS24
        with open(self.ledger_path(), "ab") as g:
            g.write(b'{"v":2,"ts":"SECRET-FRAGMENT-TEXT')
        self.write("A", "heals the tail")
        self.ok(self.h.git("A", "add", "-A"))
        r = self.staged()
        self.assertEqual(r.returncode, 0, r.stderr)
        n = len(open(self.ledger_path(), "rb").read().split(b"\n"))
        self.assertRegex(r.stdout, r"warn: %s/\.awt/events\.jsonl:\d+: row would be quarantined" % re.escape(H.H2.TASK))
        self.assertNotIn("SECRET-FRAGMENT", r.stdout + r.stderr)
        self.assertNotIn("heals the tail", r.stdout + r.stderr)
        self.assertEqual(self.h.git("A", "commit", "-q", "-m", "ok").returncode, 0)

    def test_hs30_working_ledger_vs_head(self):  # T-HS30: HS25
        led = self.ledger_path()
        data = open(led, "rb").read()
        open(led, "wb").write(data[:len(data) // 2])
        d = self.h.awt("A", "doctor", dir=self.h.node("A", H.H2.TASK)).stdout
        self.assertIn("fail ledger is not an extension of the committed one (rows lost?)", d)
        head = self.h.git("A", "rev-parse", "HEAD").stdout.strip()
        open(os.path.join(self.h.tree("A"), ".git", "MERGE_HEAD"), "w").write(head + "\n")
        d = self.h.awt("A", "doctor", dir=self.h.node("A", H.H2.TASK)).stdout
        self.assertNotIn("not an extension", d)
        os.unlink(os.path.join(self.h.tree("A"), ".git", "MERGE_HEAD"))
        self.ok(self.h.git("A", "checkout", "--", "."))
        self.assertNotIn("not an extension", self.h.awt("A", "doctor", dir=self.h.node("A", H.H2.TASK)).stdout)
        open(led, "wb").write(data[:len(data) // 2])
        self.ok(self.h.git("A", "add", "-A"))
        self.assertEqual(self.staged().returncode, 1)  # the commit check refuses it too (HS22)

    def test_hs31_declare_and_withdraw(self):  # T-HS31: HS30
        d = self.doctor("A").stdout
        self.assertIn("ok git remote origin: declared private sync remote", d)
        self.ok(self.h.awt("A", "ref", self.h.remote, "--kind", "link", "--title", "no longer"))
        self.assertIn("warn git remote origin: not declared", self.doctor("A").stdout)
        self.ok(self.h.awt("A", "ref", self.h.remote, "--kind", "sync", "--title", "private sync remote"))
        self.assertIn("ok git remote origin: declared", self.doctor("A").stdout)
        tok = "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0" * 2
        r = self.h.awt("A", "ref", "https://x:%s@github.com/o/r" % tok, "--kind", "sync", "--title", "t")
        self.assertEqual(r.returncode, 1)
        self.assertIn("secret", r.stderr)
        self.assertNotIn(tok, r.stdout + r.stderr)
        self.assertIn("`sync` declares", " ".join(self.h.awt("A", "ref", "--help").stdout.split()))

    def test_hs32_normalisation(self):  # T-HS32: HS31
        m = mod()
        eq = ["git@github.com:Owner/Repo.git", "ssh://git@github.com/owner/repo", "https://github.com/owner/repo/", "git+ssh://git@github.com/OWNER/repo.git", "https://tok:x@github.com/Owner/Repo", "git://github.com/owner/repo.git"]
        self.assertEqual({m.norm_url(u) for u in eq}, {"github.com/owner/repo"})
        self.assertNotEqual(m.norm_url("git@github.com:owner/other.git"), m.norm_url(eq[0]))
        self.assertNotEqual(m.norm_url("git@gitlab.com:owner/repo.git"), m.norm_url(eq[0]))
        self.assertEqual(m.norm_url("git@git.example.com:Team/Repo.git"), "git.example.com/Team/Repo")  # only github.com lowercases the path
        self.assertEqual(m.norm_url(self.h.remote), self.h.remote)
        self.assertEqual(m.norm_url("file://" + self.h.remote), self.h.remote)
        link = os.path.join(self.h.T, "link.git")
        os.symlink(self.h.remote, link)
        self.assertEqual(m.norm_url(link), self.h.remote)

    def test_hs33_doctor_lines(self):  # T-HS33: HS32
        self.ok(self.h.git("A", "remote", "add", "extra", "https://user:s3cretpw@git.example.com/x/y.git"))
        self.ok(self.h.git("A", "remote", "add", "mixed", self.h.remote))
        self.ok(self.h.git("A", "remote", "set-url", "--push", "mixed", "https://user:s3cretpw@git.example.com/x/z.git"))
        self.ok(self.h.awt("A", "ref", "git@git.example.com:gone/away.git", "--kind", "sync", "--title", "declared, not configured"))
        d = self.doctor("A").stdout
        self.assertIn("ok git remote origin: declared private sync remote", d)
        self.assertRegex(d, r"warn git remote extra: not declared; task data would be pushed if committed; if it is private: awt ref URL --kind sync --title \"private sync remote\"")
        self.assertIn("warn git remote mixed: not declared", d)
        self.assertIn("warn git remote extra: visibility not checked (only github.com is probed)", d)
        self.assertIn("warn declared sync remote not configured in git: git.example.com/gone/away", d)
        self.assertNotIn("s3cretpw", d)
        self.assertNotIn("user:", d)

    def test_hs34_public_probe(self):  # T-HS34: HS33
        seen, status, delay = [], [200], [0]

        class Stub(http.server.BaseHTTPRequestHandler):
            def do_HEAD(s):
                seen.append((s.path, dict(s.headers)))
                time.sleep(delay[0])
                s.send_response(status[0])
                s.end_headers()

            def log_message(s, *a):
                pass
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stub)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        self.ok(self.h.git("A", "remote", "add", "extra", "git@github.com:parsekit-bot/other.git"))
        env = dict(over={"AWT_TEST_GITHUB_BASE": base})
        d = self.h.awt("A", "doctor", **env)
        self.assertEqual(d.returncode, 1, d.stdout)
        self.assertIn("fail git remote extra is public: task data must not go there", d.stdout)
        self.assertEqual(seen[0][0], "/parsekit-bot/other")
        status[0] = 404
        d = self.h.awt("A", "doctor", **env)
        self.assertNotIn("visibility", d.stdout)
        self.assertNotIn("is public", d.stdout)
        status[0] = 500
        self.assertIn("warn git remote extra: visibility not checked (HTTP 500)", self.h.awt("A", "doctor", **env).stdout)
        delay[0], status[0] = 6, 200
        t0 = time.time()
        d = self.h.awt("A", "doctor", **env)
        self.assertLess(time.time() - t0, 5.9 + 3)
        self.assertIn("visibility not checked (OFFLINE)", d.stdout)
        delay[0] = 0
        n = len(seen)
        self.assertEqual(self.staged().returncode, 0)
        self.assertEqual(len(seen), n)  # doctor --staged makes no request
        for _, hd in seen:
            self.assertFalse({k.lower() for k in hd} & {"authorization", "cookie"})
            self.assertEqual(hd.get("User-Agent"), "awt-doctor")
        srv.shutdown()
        srv.server_close()
        self.assertIn("visibility not checked (OFFLINE)", self.h.awt("A", "doctor", **env).stdout)  # connection refused
        self.ok(self.h.awt("A", "ref", "https://github.com/parsekit-bot/other", "--kind", "sync", "--title", "declared"))
        self.assertIn("ok git remote extra: declared private sync remote", self.h.awt("A", "doctor", **env).stdout)

    def test_hs34b_nested_work_tree(self):  # HS34: a node inside the tree's repo is not checked; the top of its own work tree is
        nested = self.h.node("A", H.H2.TASK)
        d = self.h.awt("A", "doctor", dir=nested).stdout
        self.assertNotIn("git remote", d.replace("ok no git remote", ""))
        self.ok(self.h.git("A", "rev-parse", "--show-toplevel"))
        self.assertEqual(subprocess.run(["git", "init", "-q", nested], capture_output=True, env=H.clean_env(self.h.T, self.h.T)).returncode, 0)
        self.ok(subprocess.run(["git", "-C", nested, "remote", "add", "origin", "https://git.example.com/x/y"], capture_output=True, text=True, env=H.clean_env(self.h.T, self.h.T)))
        d = self.h.awt("A", "doctor", dir=nested).stdout
        self.assertIn("warn git remote origin: not declared", d)

    def test_hs8x_legacy_doctor_has_no_new_lines(self):  # IS6: no sync lines outside a declared top
        d = self.h.awt("A", "doctor", dir=self.h.node("A", H.H2.TASK)).stdout
        self.assertNotIn("does not ignore", d)
        self.assertNotIn("pre-commit hook", d)


class Stores(unittest.TestCase):
    """Two stores with Claude transcripts that run Bash tool calls; the tree is the H2 tree."""

    @classmethod
    def setUpClass(cls):
        if not HAVE_GIT:
            raise unittest.SkipTest("git is not installed")

    def setUp(self):
        self.h = H.H2()
        self.addCleanup(self.h.cleanup)
        self.h.setup()
        self.repos = os.path.join(self.h.T, "repos")
        for name, files in (("parsekit", ("Cargo.toml", "a.rs", "b.rs")), ("ledgerline", ("package.json",))):
            d = os.path.join(self.repos, name)
            os.makedirs(d)
            for f in files:
                open(os.path.join(d, f), "w").write("x\n")
            subprocess.run(["git", "init", "-q", d], env=H.clean_env(self.h.T, self.h.T), check=True)
            subprocess.run(["git", "-C", d, "add", "-A"], env=H.clean_env(self.h.T, self.h.T), check=True)
            subprocess.run(["git", "-C", d, "commit", "-q", "-m", "i"], env=H.clean_env(self.h.T, self.h.T), check=True)

    def session(self, host, sid, cwd, cmds, words="tokenizer"):
        proj = os.path.join(self.h.T, host, "home", ".claude", "projects", "-work-" + sid[:6])
        os.makedirs(proj, exist_ok=True)
        base = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
        rows = []
        for i, c in enumerate([None] + list(cmds)):
            stamp = (base + datetime.timedelta(seconds=i * 5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            if c is None:
                r = rec("user", 0, "work on %s" % words)
            else:
                r = tool_use(i, "t%d" % i, "Bash", {"command": c})
            r.update(sessionId=sid, cwd=cwd, timestamp=stamp)
            r["uuid"] = "%s-u%d" % (sid[:4], i)
            r["parentUuid"] = "%s-u%d" % (sid[:4], i - 1) if i else None
            rows.append(r)
        with open(os.path.join(proj, sid + ".jsonl"), "w") as g:
            for r in rows:
                g.write(json.dumps(r) + "\n")

    def awt(self, h, *a, **kw):
        return self.h.awt(h, *a, **kw)

    def ingest(self, h, *a):
        r = self.awt(h, "ingest", *a)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def dump(self, h):
        return H.logical(os.path.join(self.h.T, h, "store", "store.db"))

    def digest(self, h):
        return open(os.path.join(self.h.T, h, "store", "store.db"), "rb").read()

    def world(self):
        pk, ll = os.path.join(self.repos, "parsekit"), os.path.join(self.repos, "ledgerline")
        self.session("A", "aaaa0000-0000-4000-8000-000000000001", pk, ["cargo test", "cargo build", "cargo test --all", "cargo test x", "cargo test y", "cargo test z", "ls"], "alphaword")
        self.session("B", "bbbb0000-0000-4000-8000-000000000002", ll, ["adb devices", "ffmpeg -i x y", "ls", "pwd"], "betaword")
        self.ingest("A")
        self.ingest("B")

    def tree_sync(self):
        for r in self.h.cutover():
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_hs35_store_after_rsync_and_pull(self):  # T-HS35: HS40
        self.world()
        self.assertEqual(H.rsync(os.path.join(self.h.T, "A", "store"), os.path.join(self.h.T, "B", "store")), [])
        H.rsync(os.path.join(self.h.T, "B", "store"), os.path.join(self.h.T, "A", "store"))
        self.write_note("A", "note from a")
        self.tree_sync()
        for h in "AB":
            self.ingest(h)
            c = sqlite3.connect("file:%s?mode=ro" % os.path.join(self.h.T, h, "store", "store.db"), uri=True)
            sids = {r[0] for r in c.execute("select session_id from sessions")}
            texts = [r[0] for r in c.execute("select fields from records where type='note'")]
            c.close()
            self.assertEqual(sids, {"aaaa0000-0000-4000-8000-000000000001", "bbbb0000-0000-4000-8000-000000000002"})
            self.assertTrue(any("note from a" in t for t in texts))
            before = self.dump(h)
            self.ingest(h, "--rebuild")
            self.assertEqual(self.dump(h), before)  # IS5: incremental update equals a rebuild

    def write_note(self, h, text):
        r = self.h.awt(h, "note", text, dir=self.h.node(h, H.H2.TASK))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_hs36_reimport_changes_nothing(self):  # T-HS36: HS42
        self.world()
        H.rsync(os.path.join(self.h.T, "A", "store"), os.path.join(self.h.T, "B", "store"))
        self.tree_sync()
        self.ingest("B")
        d0 = self.digest("B")
        H.rsync(os.path.join(self.h.T, "A", "store"), os.path.join(self.h.T, "B", "store"))  # the same rsync twice
        self.tree_sync()  # the same pull: nothing new
        r = self.ingest("B")
        self.assertEqual(self.digest("B"), d0)
        self.assertNotIn("ingested 1", r.stdout)
        self.assertIn("ingested 0 rows", r.stdout)

    def test_hs37_partial_copy(self):  # T-HS37: HS43
        self.world()
        src, dst = os.path.join(self.h.T, "A", "store"), os.path.join(self.h.T, "B", "store")
        files = [os.path.relpath(os.path.join(dp, f), src) for dp, _, fns in os.walk(os.path.join(src, "log")) for f in fns]
        self.assertTrue(files)
        full = os.path.getsize(os.path.join(src, files[0]))
        H.rsync(src, dst, stop=(files[0], full // 2 + 1))  # cut mid-line
        r = self.ingest("B")
        self.assertNotIn("failed", r.stdout)
        self.assertEqual(self.awt("B", "doctor").stdout.count("ingest error"), 0)
        H.rsync(src, dst)
        self.ingest("B")
        got = self.dump("B")
        self.ingest("B", "--rebuild")
        self.assertEqual(self.dump("B"), got)

    def profiles(self, h):
        p = os.path.join(self.h.T, h, "store", "views", "profiles.json")
        return json.load(open(p)), p

    def test_hs38_profiles_file(self):  # T-HS38: HS50, HS51
        self.world()
        doc, p = self.profiles("A")
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(p)).st_mode), 0o700)
        self.assertEqual((doc["v"], doc["host"], doc["window_days"]), (1, "host-a", 90))
        self.assertEqual([f for f in os.listdir(os.path.dirname(p)) if f.endswith(".tmp")], [])
        os.unlink(p)
        self.ingest("A")  # missing: rebuilt although the store is fresh
        self.assertTrue(os.path.exists(p))
        old = time.time() - 3 * 86400
        os.utime(p, (old, old))
        self.ingest("A")
        self.assertGreater(os.path.getmtime(p), old + 86400)
        h = json.load(open(p))["built"]
        # a hook run over budget keeps the old file and records the error
        env = dict(AWT_TEST_BUILD_SLEEP=None)
        m = mod(self.h.tree("A"))
        os.utime(p, (old, old))
        before = open(p, "rb").read()
        r = subprocess.run([sys.executable, "-I", "-c", "import sys, importlib.machinery as m, importlib.util as u, time\nl = m.SourceFileLoader('a', %r)\ns = u.spec_from_loader('a', l)\nx = u.module_from_spec(s)\nl.exec_module(x)\nx.build_profiles = lambda store, deadline=None: (_ for _ in ()).throw(TimeoutError('over budget'))\nx.refresh_profiles(%r, None, True)\n" % (AWT, os.path.join(self.h.T, "A", "store"))], capture_output=True, text=True, env=self.h.env("A"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(open(p, "rb").read(), before)
        self.assertIn("ingest error for profiles: TimeoutError: over budget", self.awt("A", "doctor").stdout)
        self.ingest("A")
        self.assertEqual(self.awt("A", "doctor").stdout.count("ingest error for profiles"), 0)

    def test_hs38b_old_store_gets_no_profile(self):  # T-HS38: a store of another schema writes none
        self.world()
        p = os.path.join(self.h.T, "A", "store", "views", "profiles.json")
        os.unlink(p)
        c = sqlite3.connect(os.path.join(self.h.T, "A", "store", "store.db"))
        c.execute("update schema_meta set value='1' where key='schema_version'")
        c.commit()
        c.close()
        self.awt("A", "ingest")
        self.assertFalse(os.path.exists(p))

    def test_hs39_head_extraction(self):  # T-HS39: HS53
        m = mod()
        got = m.command_heads("FOO=1 sudo env cargo test --all --token=sekrit && cd x | tee /tmp/secret.log")
        self.assertEqual([h for _, h in got], ["cargo test", "tee"])
        self.assertEqual(m.command_heads("ls $(cat /etc/passwd) 'arg with spaces'")[0], ("other", "ls"))
        self.assertEqual(m.command_heads("/usr/bin/cargo test")[0], ("other", "other"))
        pk = os.path.join(self.repos, "parsekit")
        self.session("A", "cccc0000-0000-4000-8000-000000000003", pk, ["curl -H 'Authorization: Bearer topsecretvalue' https://x.invalid/path", "cargo test --features argmarker"])
        self.ingest("A")
        raw = open(self.profiles("A")[1]).read()
        for needle in ("topsecretvalue", "argmarker", "x.invalid", "Authorization"):
            self.assertNotIn(needle, raw)

    def test_hs40_class_table(self):  # T-HS40: HS53
        m = mod()
        cases = {"device": ["adb devices", "emulator -avd x", "fastboot flash", "xcrun simctl list", "xcrun devicectl x", "idevicesyslog", "ios-deploy -b x", "maestro test x"],
                 "media": ["ffmpeg -i a b", "ffprobe x", "magick a b", "convert a b", "sips -z 1 1 a", "sox a b"],
                 "test": ["pytest -q", "python3 -m pytest", "python -m unittest", "cargo test", "go test ./...", "jest", "vitest run", "playwright test", "swift test", "npm test", "pnpm test", "yarn test", "bun test",
                          "npm run test:unit", "gradle testDebug", "./gradlew connectedTest", "xcodebuild test -scheme x"],
                 "build": ["make", "cmake .", "ninja", "bazel build //x", "cargo build", "cargo run", "cargo check", "cargo clippy", "go build ./...", "gradle assemble", "./gradlew assemble", "mvn package", "xcodebuild -scheme x",
                           "swift build", "tsc", "webpack", "vite build", "docker build .", "npm run build:prod"],
                 "install": ["npm install", "pnpm ci", "yarn add x", "bun add x", "pip install x", "uv sync", "uv pip install x", "cargo install x", "brew install x", "apt install x", "apt-get install x", "pod install", "bundle install"],
                 "other": ["ls", "git status", "echo hi", "python script.py", "npm publish"]}
        for cls, cmds in cases.items():
            for c in cmds:
                self.assertEqual(m.command_heads(c)[0][0], cls, c)

    def counts(self, **c):
        base = {k: 0 for k in ("build", "test", "install", "device", "media", "other")}
        base.update(c)
        return base

    def test_hs41_class_rules(self):  # T-HS41: HS55
        m = mod()
        f = m.class_of
        self.assertEqual(f("light", self.counts(device=9), ["Cargo.toml"], 9999), ("light", "override"))
        self.assertEqual(f(None, self.counts(device=2, media=1), [], 0), ("media-device", "observed"))
        self.assertEqual(f(None, self.counts(device=1, media=1, other=50), [], 0), ("light", "default"))
        self.assertEqual(f(None, self.counts(build=2, test=2, install=1, other=5), [], 0), ("build-heavy", "observed"))
        self.assertEqual(f(None, self.counts(build=2, test=2, other=5), [], 0), ("light", "default"))  # 4 calls
        self.assertEqual(f(None, self.counts(build=5, other=45), [], 0), ("build-heavy", "observed"))  # exactly 10%
        self.assertEqual(f(None, self.counts(build=5, other=46), [], 0), ("light", "default"))  # under 10%
        self.assertEqual(f(None, self.counts(), ["Cargo.toml"], 3), ("build-heavy", "manifest"))
        self.assertEqual(f(None, self.counts(), ["package.json"], 3), ("light", "default"))
        self.assertEqual(f(None, self.counts(), [], 5001), ("build-heavy", "manifest"))
        self.assertEqual(f(None, self.counts(), [], 5000), ("light", "default"))

    def test_hs42_missing_repo_and_unassigned(self):  # T-HS42: HS52
        self.world()
        self.session("B", "dddd0000-0000-4000-8000-000000000004", os.path.join(self.repos, "parsekit"), ["ls"])
        self.ingest("B")
        doc, _ = self.profiles("B")
        self.assertIn(os.path.join(self.repos, "parsekit"), doc["repos"])
        self.assertIsNone(doc["repos"][os.path.join(self.repos, "parsekit")]["project"])  # no node: unassigned
        self.session("B", "eeee0000-0000-4000-8000-000000000005", "/nonexistent/on/this/host", ["cargo test"])
        self.ingest("B")
        doc, _ = self.profiles("B")
        self.assertNotIn("/nonexistent/on/this/host", doc["repos"])
        # a project's sessions count even when its repo is absent here: place a session in the project node
        task = self.h.node("B", H.H2.TASK)
        self.session("B", "ffff0000-0000-4000-8000-000000000006", task, ["cargo test"] * 3 + ["make", "make", "ls"])
        self.ingest("B")
        doc, _ = self.profiles("B")
        proj = [p for p in doc["projects"].values() if p["sessions"]]
        self.assertTrue(proj)
        self.assertEqual(proj[0]["commands"]["test"], 3)
        self.assertEqual(proj[0]["class"], "build-heavy")

    def test_hs43_override_tag(self):  # T-HS43: HS56
        task = self.h.node("A", H.H2.TASK)
        r = self.h.awt("A", "decide", "x", "--why", "w", "--tag", "profile:heavy", dir=task)
        self.assertEqual(r.returncode, 1)
        self.assertIn("fix: use --tag profile:light|build-heavy|media-device", r.stderr)
        proj = self.h.node("A", "projects/parsekit")
        self.session("A", "aaaa1111-0000-4000-8000-000000000011", task, ["ls"])
        r = self.h.awt("A", "decide", "parsekit is build work", "--why", "w", "--tag", "profile:build-heavy", dir=proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        d1 = re.search(r"(d-[0-9a-f]{8})", r.stdout).group(1)
        self.ingest("A")
        doc, _ = self.profiles("A")
        self.assertEqual((doc["projects"]["path:projects/parsekit"]["class"], doc["projects"]["path:projects/parsekit"]["source"]), ("build-heavy", "override"))
        r = self.h.awt("A", "decide", "no it is light", "--why", "w", "--tag", "profile:light", "--supersedes", d1, dir=proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.ingest("A")
        doc, _ = self.profiles("A")
        self.assertEqual((doc["projects"]["path:projects/parsekit"]["class"], doc["projects"]["path:projects/parsekit"]["source"]), ("light", "override"))

    def test_hs44_shape(self):  # T-HS44: HS57
        self.world()
        _, p = self.profiles("A")
        raw = open(p).read()
        doc = json.loads(raw)
        self.assertEqual(raw, json.dumps(doc, sort_keys=True, separators=(",", ":")))
        self.assertEqual(doc["v"], 1)
        for e in list(doc["repos"].values()) + list(doc["projects"].values()):
            self.assertLessEqual(len(e["heads"]), 10)
            self.assertEqual(set(e["commands"]), {"build", "test", "install", "device", "media", "other"})
            self.assertIn(e["class"], ("light", "build-heavy", "media-device"))
            self.assertIn(e["source"], ("override", "observed", "manifest", "default"))
        pk = doc["repos"][os.path.join(self.repos, "parsekit")]
        self.assertEqual((pk["class"], pk["source"], pk["manifests"], pk["tracked_files"]), ("build-heavy", "observed", ["Cargo.toml"], 3))
        self.assertIn(["cargo test", 5], pk["heads"])
        self.assertNotIn("--all", raw)


if __name__ == "__main__":
    unittest.main()
