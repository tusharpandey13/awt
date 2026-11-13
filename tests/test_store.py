"""store.db (SPEC.md, "The store"): derived SQLite + FTS5 built from canonical JSONL and node logs. Fictional data in temp dirs only."""
import hashlib, json, os, sqlite3, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_awt import Base
from test_ingest import CWD, GH, SID, Ing, rec


def tool_use(i, tid, name, args, text="reading"):
    r = rec("assistant", i, text)
    r["message"]["content"].append({"type": "tool_use", "id": tid, "name": name, "input": args})
    r["message"]["model"] = "claude-test-1"
    r["message"]["stop_reason"] = "tool_use"
    return r


def result(i, tid, text, err=False):
    return rec("user", i, [{"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": err}])


class Store(Ing):
    def setUp(self):
        super().setUp()
        self.init()
        self.db = os.path.join(self.store, "store.db")

    def rows_(self):
        return [rec("user", 0, "add a tokenizer to parsekit"),
                tool_use(1, "t1", "Read", {"file_path": "lexer.py"}),
                result(2, "t1", "def lex(): pass"),
                rec("assistant", 3, "the zephyr module is done"),
                rec("user", 4, "now add tests for the zephyr tokenizer"),
                rec("assistant", 5, "ok")]

    def build(self, rows=None, *extra):
        self.put(rows if rows is not None else self.rows_())
        return self.ok("ingest", "--source", "claude", *extra, root=self.root)

    def q(self, sql, *args):
        c = sqlite3.connect("file:%s?mode=ro" % self.db, uri=True)
        try:
            return c.execute(sql, args).fetchall()
        finally:
            c.close()

    def digest(self):
        with open(self.db, "rb") as g:
            return hashlib.sha256(g.read()).hexdigest()

    def dump(self):
        c = sqlite3.connect("file:%s?mode=ro" % self.db, uri=True)
        try:
            return "\n".join(c.iterdump())
        finally:
            c.close()


class TestTables(Store):
    def test_ingest_builds_a_private_db_with_every_table(self):
        self.build()
        self.assertEqual(oct(os.stat(self.db).st_mode & 0o777), "0o600")
        names = {r[0] for r in self.q("select name from sqlite_master where type='table'")}
        for t in ("projects", "nodes", "sessions", "turns", "messages", "tool_calls", "records", "effects", "ingest_sources",
                  "schema_meta", "canonical", "fts_text"):
            self.assertIn(t, names)
        meta = dict(self.q("select key, value from schema_meta"))
        self.assertEqual(meta["schema_version"], "1")
        self.assertEqual(meta["semconv_version"], "1.37.0")

    def test_sessions_turns_messages_tool_calls(self):
        self.build()
        s = self.q("select session_id, provider_name, conversation_id, node_id, join_confidence, cwd, request_model, started_at, ended_at, source, adapter from sessions")
        self.assertEqual(s, [(SID, "claude_code", SID, None, None, CWD, "claude-test-1", "2026-10-03T09:00:00.000Z", "2026-10-03T09:05:00.000Z", "claude", 1)])
        t = self.q("select turn_id, seq, started_at, ended_at, outcome, paseo_turn from turns order by seq")
        self.assertEqual(t, [(SID + ":0", 0, "2026-10-03T09:00:00.000Z", "2026-10-03T09:03:00.000Z", None, 0),
                             (SID + ":1", 1, "2026-10-03T09:04:00.000Z", "2026-10-03T09:05:00.000Z", None, 0)])  # a tool_result is not a turn boundary
        m = self.q("select message_id, turn_id, role, text, parent_id, response_finish_reasons from messages order by seq")
        self.assertEqual(len(m), 6)
        self.assertEqual(m[0], ("u-0", SID + ":0", "user", "add a tokenizer to parsekit", None, None))
        self.assertEqual(m[1][5], '["tool_use"]')
        self.assertEqual(m[2][1], SID + ":0")
        self.assertEqual(m[4][1], SID + ":1")
        c = self.q("select tool_call_id, message_id, tool_name, args, result_excerpt, result_sha256, is_error, started_at, ended_at from tool_calls")
        self.assertEqual(c, [("t1", "u-1", "Read", '{"file_path":"lexer.py"}', "def lex(): pass", hashlib.sha256(b"def lex(): pass").hexdigest(), 0,
                              "2026-10-03T09:01:00.000Z", "2026-10-03T09:02:00.000Z")])

    def test_canonical_keeps_the_raw_record_and_nothing_is_redacted_or_cut(self):
        big = "start " + "x" * 300000 + " tailword"
        rows = [rec("user", 0, "token " + GH + " here"), rec("assistant", 1, big)]
        self.build(rows)
        raw = [json.loads(r[0]) for r in self.q("select raw from canonical order by seq")]
        self.assertEqual(raw, rows)
        self.assertEqual(self.q("select text from messages where message_id='u-0'"), [("token " + GH + " here",)])
        self.assertEqual(self.q("select length(text) from messages where message_id='u-1'"), [(len(big),)])
        self.assertEqual(self.q("select json_extract(raw, '$.message.role') from canonical where seq=0"), [("user",)])

    def test_fts_covers_messages_and_tool_args_and_caps_only_the_index(self):
        big = "start " + "x" * 300000 + " tailword"
        self.build(self.rows_() + [rec("assistant", 6, big)])
        hit = lambda w: self.q("select kind from fts_text where fts_text match ? order by rowid", w)
        self.assertEqual(hit('"zephyr"'), [("message",), ("message",)])
        self.assertEqual(hit('"lexer"'), [("tool_call",)])
        self.assertEqual(hit('"start"'), [("message",)])
        self.assertEqual(hit('"tailword"'), [])  # past the 256 KiB index cap; the message row still holds it
        self.assertIn("tailword", self.q("select text from messages where message_id='u-6'")[0][0])

    def test_records_effects_nodes_and_projects(self):
        n = self.ok("note", "tokenizer notes", root=self.root).stdout.split()[0]
        d = self.ok("decide", "use a trie", "--why", "fast lookups", "--related", "0", root=self.root).stdout.split()[0]
        e = self.plan()
        self.ok("effect", "begin", e)
        self.ok("effect", "mark", e, "sent", "--ref", "https://example.invalid/m/1")
        self.build()
        r = {x[0]: x for x in self.q("select record_id, type, by, origin, json_extract(fields, '$.text') from records")}
        self.assertEqual(r[n][1:], ("note", "agent", "agent", "tokenizer notes"))
        self.assertEqual(r[d][1], "decision")
        self.assertEqual(len(self.q("select 1 from records where type='effect'")), 3)  # one row per step
        self.assertEqual(len({x[0] for x in self.q("select record_id from records")}), len(self.q("select record_id from records")))
        ef = self.q("select effect_id, target, state, attempt, origin, begun_by, sent_ref, tool_call_id from effects")
        self.assertEqual(ef, [(e, "slack:#eng", "sent", 1, "declared", "agent", "https://example.invalid/m/1", None)])
        nodes = self.q("select node_id, kind, path, parent_id, project_id, status from nodes")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0][2:], (".", None, "unassigned", "active"))
        self.assertEqual(self.q("select project_id from projects"), [("unassigned",)])
        self.assertEqual(self.q("select count(*) from fts_text where kind='record'"), [(len(self.q("select 1 from records")),)])

    def test_session_joins_a_node_only_on_an_exact_cwd(self):
        rows = [dict(r, cwd=self.root) for r in self.rows_()]
        self.build(rows)
        self.assertEqual(self.q("select node_id is not null, join_confidence from sessions"), [(1, "cwd")])
        self.assertEqual(self.q("select count(*) from sessions s join nodes n using (node_id)"), [(1,)])

    def test_unparsed_rows_and_ingest_sources(self):
        self.put([self.rows_()[0], b"not json at all\n"])
        self.ok("ingest", "--source", "claude", root=self.root)
        self.assertEqual(self.q("select count(*) from canonical"), [(2,)])
        self.assertEqual(self.q("select count(*) from messages"), [(1,)])
        s = self.q("select source, path, adapter, errors from ingest_sources")
        self.assertEqual(s, [("claude", "-work-parsekit/%s.jsonl" % SID, 1, 1)])

    def test_no_canonical_still_builds_an_empty_db(self):
        self.ok("ingest", "--source", "claude", root=self.root)
        self.assertEqual(self.q("select count(*) from sessions"), [(0,)])
        self.assertEqual(self.q("select count(*) from nodes"), [(1,)])


class TestRebuild(Store):
    def test_rebuild_is_byte_stable_and_never_reads_the_provider(self):
        self.ok("note", "tokenizer notes", root=self.root)
        self.build()
        want, dump = self.digest(), self.dump()
        self.ok("ingest", "--rebuild", root=self.root)
        self.assertEqual(self.digest(), want)  # the db file itself is identical
        os.rename(self.proj, self.proj + ".gone")  # providers are not read by --rebuild
        self.ok("ingest", "--rebuild", root=self.root)
        self.assertEqual(self.digest(), want)
        self.assertEqual(self.dump(), dump)

    def test_rebuild_from_scratch_equals_the_incremental_build(self):
        self.build()
        self.build_more = self.put(self.rows_() + [rec("user", 6, "one more thing")])
        self.ok("ingest", "--source", "claude", root=self.root)
        inc = self.digest()
        os.unlink(self.db)
        self.ok("ingest", "--rebuild", root=self.root)
        self.assertEqual(self.digest(), inc)

    def test_rebuild_replaces_a_broken_db_and_leaves_no_temp_files(self):
        self.build()
        want = self.digest()
        with open(self.db, "wb") as g:
            g.write(b"garbage" * 100)
        self.ok("ingest", "--rebuild", root=self.root)
        self.assertEqual(self.digest(), want)
        self.assertEqual(sorted(f for f in os.listdir(self.store) if f.startswith("store.db")), ["store.db"])

    def test_normal_ingest_recovers_a_broken_db(self):
        self.build()
        with open(self.db, "wb") as g:
            g.write(b"garbage")
        self.ok("ingest", "--source", "claude", root=self.root)
        self.assertEqual(self.q("select count(*) from messages"), [(6,)])

    def test_normal_ingest_updates_and_an_unchanged_run_leaves_the_db_alone(self):
        self.build()
        before = os.stat(self.db).st_mtime_ns
        self.ok("ingest", "--source", "claude", root=self.root)
        self.assertEqual(os.stat(self.db).st_mtime_ns, before)
        self.ok("note", "a new record", root=self.root)
        self.ok("ingest", "--source", "claude", root=self.root)  # a node log changed: the db follows
        self.assertEqual(self.q("select count(*) from records where json_extract(fields, '$.text')='a new record'"), [(1,)])
        self.put(self.rows_() + [rec("assistant", 6, "late message")])
        self.ok("ingest", "--source", "claude", root=self.root)
        self.assertEqual(self.q("select count(*) from messages"), [(7,)])

    def test_rebuild_output_and_hook(self):
        self.build()
        r = self.ok("ingest", "--rebuild", root=self.root)
        self.assertIn("store.db", r.stdout)
        self.assertNotIn("claude files", r.stdout)  # no provider was read
        h = self.ok("ingest", "--rebuild", "--hook", root=self.root)
        self.assertEqual((h.stdout, h.stderr), ("", ""))


class TestFind(Store):
    def test_default_find_is_literal_and_never_touches_messages(self):
        self.ok("note", "zephyr in the notes", root=self.root)
        self.build()
        out = self.ok("find", "zephyr", root=self.root).stdout
        self.assertIn("zephyr in the notes", out)
        self.assertNotIn("message:", out)

    def test_sessions_adds_message_and_tool_call_hits(self):
        self.ok("note", "zephyr in the notes", root=self.root)
        self.build()
        out = self.ok("find", "--sessions", "zephyr", root=self.root).stdout.splitlines()
        self.assertTrue(any("zephyr in the notes" in l for l in out), out)
        msgs = [l for l in out if l.startswith("message:")]
        self.assertEqual(len(msgs), 2, out)
        self.assertTrue(all(l.startswith("message:%s#" % SID) for l in msgs), msgs)
        self.assertIn("[assistant]", " ".join(msgs))
        tools = self.ok("find", "--sessions", "lexer", root=self.root).stdout.splitlines()
        self.assertEqual([l for l in tools if l.startswith("tool_call:")], ["tool_call:%s:t1 [Read]: {\"file_path\":\"lexer.py\"}" % SID])

    def test_sessions_without_a_store_says_so_and_keeps_records(self):
        self.ok("note", "zephyr in the notes", root=self.root)
        out = self.ok("find", "--sessions", "zephyr", root=self.root).stdout.splitlines()
        self.assertTrue(any("zephyr in the notes" in l for l in out), out)
        self.assertEqual(out[-1], "note: no store.db yet (run awt ingest); sessions not searched")

    def test_sessions_with_a_broken_store_does_not_fail(self):
        os.makedirs(self.store)
        with open(self.db, "wb") as g:
            g.write(b"garbage" * 50)
        r = self.ok("find", "--sessions", "zephyr", root=self.root)
        self.assertIn("note:", r.stdout)

    def test_sessions_needs_a_term_and_not_like(self):
        self.bad("find", "--sessions", root=self.root, code=2)
        self.bad("find", "--sessions", "--like", "some text", root=self.root, code=2)

    def test_like_ignores_the_store_and_works_without_one(self):
        self.ok("note", "gateway timeout is thirty seconds", root=self.root)
        want = self.ok("find", "--like", "gateway timeout seconds", root=self.root).stdout
        self.assertIn("gateway timeout is thirty seconds", want)
        self.build()
        self.assertEqual(self.ok("find", "--like", "gateway timeout seconds", root=self.root).stdout, want)


class TestDoctor(Store):
    def test_fts5_ok_and_missing(self):
        out = self.awt("doctor").stdout
        self.assertRegex(out, r"ok .*FTS5")
        env = dict(self.env, AWT_TEST_NO_FTS5="1")
        r = self.awt("doctor", env=env)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertRegex(r.stdout, r"fail .*FTS5")

    def test_ingest_and_find_say_so_when_fts5_is_missing(self):
        env = dict(self.env, AWT_TEST_NO_FTS5="1")
        r = self.awt("ingest", "--rebuild", root=self.root, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("FTS5", r.stderr)
        self.assertIn("fix:", r.stderr)


if __name__ == "__main__":
    unittest.main()
