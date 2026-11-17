"""Review fixes for PR #23 (H1 store rebuild safety, M1 ui live read-only, M2 out-of-range ints, M3 supersede hint, L1-L4). Fictional parsekit data in temp dirs only; the real store is never touched."""
import glob, json, os, shutil, sqlite3, subprocess, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_awt import AWT
from test_ingest import SID, rec
from test_usage import FX, SID2, Usage, asst, sess

REAL = os.path.join(FX, "real-20.0.51")


class Old(Usage):
    """A store built by this awt, then made to look like an older schema."""

    def old_store(self, rows=None, version="5"):
        self.put(rows or [rec("user", 0, "add a tokenizer"), asst(1, "done", "m1", 100, 40)])
        self.ok("ingest", "--source", "claude", root=self.root)
        c = sqlite3.connect(self.db)
        c.execute("UPDATE schema_meta SET value=? WHERE key='schema_version'", (version,))
        c.commit()
        c.close()
        with open(self.db, "rb") as g:
            self.before = g.read()

    def untouched(self):
        with open(self.db, "rb") as g:
            self.assertEqual(g.read(), self.before)
        self.assertEqual([f for f in os.listdir(self.store) if f.endswith(".tmp")], [])


class TestSchemaBumpNeverRebuildsUnasked(Old):
    def more(self):
        self.put([rec("user", 0, "add a tokenizer"), asst(1, "done", "m1", 100, 40), rec("user", 2, "and tests"), asst(3, "ok", "m2", 5, 5)])

    def test_hook_and_pipe_leave_an_old_store_alone_and_silent(self):
        self.old_store()
        self.more()
        for args in (("--source", "claude", "--hook"), ("--source", "all", "--hook")):
            r = self.ok("ingest", *args, root=self.root)
            self.assertEqual((r.stdout, r.stderr), ("", ""))
        r = self.ok("ingest", "--source", "paseo", "--stdin", root=self.root, input="")
        self.assertNotIn("rebuilt", r.stdout)
        self.untouched()  # not rebuilt, not updated; find still reads it
        self.assertIn("tokenizer", self.ok("find", "--sessions", "tokenizer", root=self.root).stdout)

    def test_plain_ingest_warns_and_does_not_rebuild_either(self):
        self.old_store()
        self.more()
        r = self.ok("ingest", "--source", "claude", root=self.root)
        self.assertIn("store schema 5 < 7", r.stderr)
        self.assertIn("awt ingest --rebuild", r.stderr)
        self.assertNotIn("rebuilt", r.stdout + r.stderr)
        self.untouched()

    def test_doctor_warns_and_only_rebuild_replaces_it(self):
        self.old_store()
        self.more()
        self.ok("ingest", "--source", "claude", root=self.root)  # copies the new transcript rows into the canonical log; the store stays old
        d = self.awt("doctor", root=self.root)
        self.assertRegex(d.stdout + d.stderr, r"warn.*store schema 5 < 7: run `awt ingest --rebuild` once")
        r = self.ok("ingest", "--rebuild", root=self.root)
        self.assertIn("rebuilt store.db", r.stdout)
        self.assertEqual(self.q("select value from schema_meta where key='schema_version'"), [("7",)])
        self.assertEqual(self.q("select count(*) from messages"), [(4,)])  # the canonical rows ingested meanwhile are in it
        d = self.awt("doctor", root=self.root)
        self.assertNotIn("store schema", d.stdout + d.stderr)

    def test_a_broken_store_is_not_replaced_by_a_plain_ingest_either(self):
        self.old_store()
        with open(self.db, "wb") as g:
            g.write(b"garbage")
        self.before = b"garbage"
        r = self.ok("ingest", "--source", "claude", root=self.root)
        self.assertIn("awt ingest --rebuild", r.stderr)
        self.untouched()

    def sparse_log(self, mb):
        big = os.path.join(self.store, "log", "claude", "2026-10", "big.jsonl")
        os.makedirs(os.path.dirname(big), exist_ok=True)
        with open(big, "wb") as g:
            g.truncate(mb * 2 ** 20)
        return big

    def test_a_hook_builds_a_store_that_does_not_exist_yet_only_while_the_logs_are_small(self):
        self.put([rec("user", 0, "hi"), asst(1, "ok", "m1", 1, 1)])
        self.ok("ingest", "--source", "claude", "--hook", root=self.root)
        self.assertEqual(self.q("select count(*) from messages"), [(2,)])
        os.unlink(self.db)
        big = self.sparse_log(65)  # past the cap of 64 MB of canonical logs
        self.ok("ingest", "--source", "claude", "--hook", root=self.root)
        self.assertFalse(os.path.exists(self.db))  # the hook did nothing heavy
        os.unlink(big)
        self.ok("ingest", "--source", "claude", "--hook", root=self.root)
        self.assertTrue(os.path.exists(self.db))


class TestRebuildNeedsDisk(Old):
    def test_refused_with_a_fix_line_when_the_disk_is_too_full(self):
        self.old_store()
        env = dict(self.env, AWT_TEST_FREE_BYTES="1000")
        r = self.bad("ingest", "--rebuild", root=self.root, env=env)
        self.assertIn("not enough free disk", r.stderr)
        self.assertRegex(r.stderr, r"fix: .*awt ingest --rebuild")
        self.assertNotIn("Traceback", r.stderr)
        self.untouched()
        h = self.ok("ingest", "--rebuild", "--hook", root=self.root, env=env)
        self.assertEqual((h.stdout, h.stderr), ("", ""))
        self.untouched()
        self.ok("ingest", "--rebuild", root=self.root, env=dict(self.env, AWT_TEST_FREE_BYTES=str(10 * 2**30)))

    def test_the_need_grows_with_the_canonical_logs(self):
        self.old_store()
        big = os.path.join(self.store, "log", "claude", "2026-10", "big.jsonl")
        with open(big, "wb") as g:
            g.truncate(200 * 2 ** 20)  # a sparse 200 MB log: needs 1.2 x 200 MB + 256 MB, about 496 MB
        r = self.bad("ingest", "--rebuild", root=self.root, env=dict(self.env, AWT_TEST_FREE_BYTES=str(400 * 2 ** 20)))
        self.assertIn("not enough free disk", r.stderr)
        self.assertRegex(r.stderr, r"about 4\d\d\.\d MB|about 4\d\d MB")
        self.untouched()


class TestLockedStore(Old):
    def test_a_lock_that_does_not_clear_never_becomes_a_full_rebuild(self):
        self.old_store(version="7")
        env = dict(self.env, AWT_TEST_BUSY_S="1")
        self.put([rec("user", 0, "add a tokenizer"), asst(1, "done", "m1", 100, 40), rec("user", 2, "more")])
        c = sqlite3.connect(self.db, isolation_level=None)
        c.execute("BEGIN EXCLUSIVE")
        try:
            r = self.ok("ingest", "--source", "claude", root=self.root, env=env)
            self.assertIn("not updated", r.stderr)
            self.assertNotIn("rebuilt", r.stdout)
            h = self.ok("ingest", "--source", "claude", "--hook", root=self.root, env=env)
            self.assertEqual((h.stdout, h.stderr), ("", ""))
        finally:
            c.execute("ROLLBACK")
            c.close()
        self.assertEqual([f for f in os.listdir(self.store) if f.endswith(".tmp")], [])
        self.untouched()
        self.ok("ingest", "--source", "claude", root=self.root)  # the lock is gone: it updates in place
        self.assertEqual(self.q("select count(*) from messages"), [(3,)])


class TestBuildMemory(Old):
    def peak_mb(self, nfiles):
        shutil.rmtree(self.store, ignore_errors=True)
        shutil.rmtree(self.pdir, ignore_errors=True)
        os.makedirs(self.pdir)
        pad = "x" * 1000
        for i in range(nfiles):
            sid = "5e5e5e5e-0000-4000-8000-0000000000%02d" % i
            self.put([dict(rec("user" if j % 2 == 0 else "assistant", j, "%s %d" % (pad, j)), sessionId=sid) for j in range(5000)], path=self.src(sid))
        self.ok("ingest", "--source", "claude", "--hook", root=self.root)  # canonical rows only: a hook leaves the large build to `ingest`
        code = "import resource, subprocess, sys; subprocess.run(sys.argv[1:], check=True, capture_output=True); print(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)"
        r = subprocess.run([sys.executable, "-I", "-c", code, sys.executable, "-I", AWT, "--dir", self.root, "ingest", "--rebuild"], env=self.env, capture_output=True, text=True, check=True)
        n = int(r.stdout.strip())
        return n / (1 if sys.platform != "darwin" else 1024) / 1024.0  # ru_maxrss: bytes on macOS, KB elsewhere

    def test_one_source_file_at_a_time_is_in_memory(self):
        one, six = self.peak_mb(1), self.peak_mb(6)
        self.assertLess(six, one + 60, "peak RSS %.0f MB for 6 files vs %.0f MB for 1: rows of every file are being kept" % (six, one))


class TestOutOfRangeNumbers(Old):
    HUGE = 10 ** 20

    def usage_rows(self):
        return self.q("select message_id, usage_input_tokens, usage_output_tokens, cache_read_tokens, latency_ms from usage where grain='message' order by message_id")

    def rows_with_huge(self):
        a = asst(1, "done", "m1", self.HUGE, 2 ** 63)
        a["message"]["usage"]["cache_read_input_tokens"] = -2 ** 63 - 1
        return [rec("user", 0, "add a tokenizer"), a, asst(2, "ok", "m2", 7, 3)]

    def test_a_huge_integer_is_stored_as_missing_and_the_build_goes_on_even_from_a_hook(self):
        self.put(self.rows_with_huge())
        r = self.ok("ingest", "--source", "claude", "--hook", root=self.root)
        self.assertEqual((r.stdout, r.stderr), ("", ""))
        self.assertEqual(self.usage_rows(), [("u-1", None, None, None, 60000), ("u-2", 7, 3, 0, 60000)])
        self.assertEqual(self.q("select count(*) from messages"), [(3,)])
        self.ok("ingest", "--rebuild", root=self.root)
        self.assertEqual(len(self.usage_rows()), 2)

    def test_a_huge_integer_in_ccusage_output_is_stored_as_missing(self):
        self.put([rec("user", 0, "add a tokenizer"), asst(1, "done", "m1", 1, 1)])
        self.ok("ingest", "--source", "claude", root=self.root)
        self.ccusage_with([(SID, "2026-10-03T10:00:00.000Z", [("claude-test-1", self.HUGE)])])
        self.ok("ingest", "--source", "ccusage", root=self.root)
        self.assertEqual(self.q("select usage_input_tokens, cost_source from usage where grain='session_model'"), [(None, "ccusage")])

    def test_a_file_that_cannot_be_derived_is_a_counted_error_and_does_not_stop_the_build(self):
        self.put([rec("user", 0, "good"), asst(1, "ok", "m1", 1, 1)])
        self.put([dict(rec("user", 0, "bad"), sessionId=SID2)], path=self.src(SID2))
        env = dict(self.env, AWT_TEST_DERIVE_RAISE=SID2)
        r = self.ok("ingest", "--source", "claude", "--hook", root=self.root, env=env)
        self.assertEqual((r.stdout, r.stderr), ("", ""))
        self.assertEqual([x[0] for x in self.q("select session_id from sessions")], [SID])
        self.assertEqual(self.q("select errors from build_state where path like ?", "%" + SID2 + ".jsonl"), [(1,)])
        self.assertEqual(self.q("select count(*) from canonical where session=?", SID2), [(1,)])  # the raw row is kept; a later awt that can derive it will
        self.ok("ingest", "--rebuild", root=self.root)
        self.assertEqual(len(self.q("select session_id from sessions")), 2)


class TestSupersedeHint(Old):
    def hint(self):
        r = self.bad("supersede", "docs/old.md", "docs/new.md", code=2, root="")
        fix = [x for x in r.stderr.splitlines() if x.startswith("fix: ")][0][5:]
        return fix.split(" && awt note")[0]

    def test_the_move_works_without_docs_superseded_and_never_replaces_an_earlier_doc(self):
        cmd = self.hint()
        w = os.path.join(self.tmp, "t")
        os.makedirs(os.path.join(w, "docs"))
        wr = lambda p, t: open(os.path.join(w, p), "w").write(t)
        wr("docs/old.md", "march plan\n")
        self.assertEqual(subprocess.run(cmd, shell=True, cwd=w).returncode, 0)  # first use: no docs/_superseded yet
        self.assertEqual(open(os.path.join(w, "docs", "_superseded", "old.md")).read(), "march plan\n")
        self.assertFalse(os.path.exists(os.path.join(w, "docs", "old.md")))
        wr("docs/old.md", "november plan\n")
        self.assertNotEqual(subprocess.run(cmd, shell=True, cwd=w, capture_output=True).returncode, 0)  # the name is taken: refused, nothing replaced
        self.assertEqual(open(os.path.join(w, "docs", "_superseded", "old.md")).read(), "march plan\n")
        self.assertEqual(open(os.path.join(w, "docs", "old.md")).read(), "november plan\n")

    def test_every_copy_of_the_hint_is_the_safe_one(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for f in ("AGENTS.md", os.path.join("docs", "adr", "0006-verb-swap.md")):
            with open(os.path.join(here, f), encoding="utf-8") as g:
                t = g.read()
            self.assertIn("mkdir -p docs/_superseded && mv -n docs/old.md", t, f)
            self.assertNotIn("`mv docs/old.md", t, f)
        self.assertIn("mv -n docs/old.md", self.ok("help", "agents", root="").stdout)


class TestRealCcusage(Usage):
    """L1: the fixture is the real output of `ccusage session --json --offline` (20.0.51) on synthetic parsekit transcripts, kept next to them."""

    def test_real_ccusage_totals_equal_ours(self):
        for f in glob.glob(os.path.join(REAL, "projects", "-work-parsekit", "*")):
            if os.path.isdir(f):
                shutil.copytree(f, os.path.join(self.pdir, os.path.basename(f)))
            else:
                shutil.copy(f, self.pdir)
        self.ok("ingest", "--source", "claude", root=self.root)
        want = json.load(open(os.path.join(REAL, "session.json")))
        self.assertEqual(want["totals"]["inputTokens"], 1107)
        self.assertEqual(self.q("select sum(usage_input_tokens) from usage_best"), [(1107,)])  # before ccusage: the transcripts alone count the copied message once
        d = os.path.join(self.tmp, "bin")
        os.makedirs(d)
        p = os.path.join(d, "ccusage")
        with open(p, "w") as g:
            g.write("#!/bin/sh\ncat '%s'\n" % os.path.join(REAL, "session.json"))
        os.chmod(p, 0o755)
        self.env["AWT_CCUSAGE"] = p
        self.ok("ingest", "--source", "ccusage", root=self.root)
        self.assertEqual(self.q("select count(*), sum(usage_input_tokens), round(sum(cost_usd), 6) from usage_best where cost_source='ccusage'"), [(2, 1107, want["totals"]["totalCost"])])
        self.assertEqual(self.q("select count(*) from usage_best"), [(2,)])  # every session of both conversations is covered once


class TestStaleCcusageCost(Usage):
    def test_a_conversation_past_the_last_import_keeps_a_floor_cost_and_its_tokens(self):
        parent = [rec("user", 0, "add a tokenizer"), asst(1, "done", "m1", 100, 0)]
        self.put(parent)
        self.put(sess([rec("user", 0, "sub task"), asst(1, "sub done", "s1", 1000, 0)], SID), path=self.src(sub="agent-x"))
        self.ok("ingest", "--source", "claude", root=self.root)
        self.ccusage_with([(SID, "2026-10-03T09:00:30.000Z", [("claude-test-1", 1100)])])  # imported before the conversation's last messages (09:01, 09:03)
        self.ok("ingest", "--source", "ccusage", root=self.root)
        self.assertEqual(self.q("select count(*) from usage_cc"), [(0,)])
        self.assertEqual(self.q("select count(*) from usage_stale"), [(1,)])
        self.assertEqual(self.q("select sum(usage_input_tokens), sum(cost_usd) from usage_best"), [(1100, 1.1)])  # tokens from the messages, cost the ccusage floor, counted once
        self.assertEqual(self.q("select cost_source, usage_input_tokens from usage_best where cost_source is not null"), [("ccusage_stale", None)])
        # the cost recipes do not lose the session
        r = self.ok("ui", "--print-metadata", root="")
        sql = json.loads(r.stdout)["databases"]["store"]["queries"]["l1_cost_sessions_agents_per_project_month"]["sql"]
        self.assertEqual(self.q("select sum(cost_usd) from (%s)" % sql.rstrip().rstrip(";")), [(1.1,)])

    def test_a_computed_cost_is_not_added_to_a_stale_ccusage_cost(self):
        self.put_pi()
        self.ok("ingest", "--source", "pi", root=self.root)
        self.assertEqual(self.q("select count(*) from usage_best where cost_usd is not null"), [(1,)])


if __name__ == "__main__":
    unittest.main()


def load_awt():
    import importlib.machinery, importlib.util
    spec = importlib.util.spec_from_loader("awtmod_v", importlib.machinery.SourceFileLoader("awtmod_v", AWT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestHuman(unittest.TestCase):
    def test_sizes_over_a_gigabyte(self):
        h = load_awt().human
        self.assertEqual(h(4053296742), "3.8 GB")
        self.assertEqual(h(3154051072), "2.9 GB")
        self.assertEqual(h(5 * 2 ** 20), "5 MB")
        self.assertEqual(h(900), "900 B")


class TestNewerStoreIsNeverTouched(Old):
    """N1: a store.db from a newer awt is never rebuilt, written or migrated by this one."""

    def newer(self):
        self.old_store(version="99")
        self.put([rec("user", 0, "add a tokenizer"), asst(1, "done", "m1", 100, 40), rec("user", 2, "and tests"), asst(3, "ok", "m2", 5, 5)])

    def test_every_ingest_mode_skips_the_store_step(self):
        self.newer()
        for args in (("--source", "claude", "--hook"), ("--source", "all", "--hook"), ("--source", "claude"), ("--rebuild",), ("--rebuild", "--hook"), ("--source", "claude", "--rebuild")):
            r = self.ok("ingest", *args, root=self.root)
            self.assertNotIn("rebuilt", r.stdout + r.stderr)
            self.untouched()
            if "--hook" in args:
                self.assertEqual((r.stdout, r.stderr), ("", ""))
        r = self.ok("ingest", "--source", "paseo", "--stdin", root=self.root, input="")
        self.untouched()
        self.assertEqual(r.stderr, "")

    def test_plain_ingest_and_rebuild_say_why_with_a_fix(self):
        self.newer()
        for args in (("--source", "claude"), ("--rebuild",)):
            r = self.ok("ingest", *args, root=self.root)
            self.assertIn("store schema 99 > 7: this awt is older than the store", r.stderr)
            self.assertIn("install the newer awt", r.stderr)

    def test_canonical_ingest_continues(self):
        self.newer()
        n = len(glob.glob(os.path.join(self.store, "log", "claude", "*", "*.jsonl")))
        self.ok("ingest", "--source", "claude", root=self.root)
        rows = sum(len(open(f).readlines()) for f in glob.glob(os.path.join(self.store, "log", "claude", "*", "*.jsonl")))
        self.assertGreaterEqual(rows, 4)
        self.assertGreaterEqual(n, 1)

    def test_doctor_warns(self):
        self.newer()
        d = self.awt("doctor", root=self.root)
        self.assertRegex(d.stdout + d.stderr, r"warn.*store schema 99 > 7: this awt is older than the store.*install the newer awt")

    def test_ui_refuses(self):
        self.newer()
        p = os.path.join(self.tmp, "fake-datasette")
        with open(p, "w") as g:
            g.write("#!/bin/sh\necho 'datasette, version 0.65.1'\n")
        os.chmod(p, 0o755)
        r = self.bad("ui", root=self.root, env=dict(self.env, AWT_DATASETTE=p))
        self.assertIn("store schema 99 > 7", r.stderr)
        self.assertIn("install the newer awt", r.stderr)


class TestUpdateRechecksSchemaUnderTheLock(Old):
    """N5"""

    def test_a_schema_that_changed_since_the_check_is_a_skip_never_a_stamp(self):
        self.old_store(version="6")
        mod = load_awt()
        store, root = self.store, self.root
        with self.assertRaises(mod.StoreChanged):
            mod.update_store(store, mod.find_root(root) or root, {})
        self.untouched()
        self.assertEqual(self.q("select value from schema_meta where key='schema_version'"), [("6",)])


class TestFullBuildGuardRollsBack(Usage):
    """N3: the per-file SAVEPOINT must undo what a failed derivation wrote, in a full build too."""

    def test_zero_rows_from_the_failed_file_and_fts_matches(self):
        self.put([rec("user", 0, "good tokenizer"), asst(1, "ok", "m1", 1, 1)])
        self.put([dict(rec("user", 0, "bad parser"), sessionId=SID2), dict(asst(1, "bad done", "m9", 4, 4), sessionId=SID2)], path=self.src(SID2))
        self.ok("ingest", "--source", "claude", root=self.root)
        good = {t: self.q("select count(*) from %s" % t)[0][0] for t in ("messages", "turns")}
        env = dict(self.env, AWT_TEST_DERIVE_RAISE_AFTER=SID2)
        self.ok("ingest", "--rebuild", root=self.root, env=env)
        for t in ("messages", "turns", "tool_calls", "usage"):
            self.assertEqual(self.q("select count(*) from %s where session_id=?" % t, SID2), [(0,)], t)
        self.assertEqual(self.q("select count(*) from sessions where session_id=?", SID2), [(0,)])
        self.assertLess(self.q("select count(*) from messages")[0][0], good["messages"])
        self.assertEqual(self.q("select count(*) from fts_text"), self.q("select count(*) from fts_ref"))
        self.assertEqual(self.q("select count(*) from fts_ref where kind='message' and ref not in (select rowid from messages)"), [(0,)])
        self.assertEqual(self.q("select errors from build_state where path like ?", "%" + SID2 + ".jsonl"), [(1,)])
        self.assertEqual(self.q("pragma integrity_check"), [("ok",)])


class TestRebuildSignals(Old):
    """N4: SIGTERM and SIGHUP during --rebuild remove the temp store.db."""

    def run_signal(self, sg):
        import signal, time
        self.old_store(version="5")
        p = subprocess.Popen([sys.executable, "-I", AWT, "--dir", self.root, "ingest", "--rebuild"], env=dict(self.env, AWT_TEST_BUILD_SLEEP="30"),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=self.tmp)
        tmps = lambda: [f for f in os.listdir(self.store) if f.startswith("store.db.") and f.endswith(".tmp")]
        end = time.time() + 20
        while time.time() < end and not tmps():
            time.sleep(0.05)
        self.assertTrue(tmps())
        p.send_signal(sg)
        p.wait(timeout=20)
        self.assertEqual(tmps(), [])
        self.untouched()

    def test_sigterm(self):
        import signal
        self.run_signal(signal.SIGTERM)

    def test_sighup(self):
        import signal
        self.run_signal(signal.SIGHUP)
