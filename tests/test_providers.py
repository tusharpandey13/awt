"""awt ingest --source opencode|pi|paseo (SPEC.md, "ingest" and "store.db"). Fixtures are fictional: fixtures/providers-v0."""
import glob, hashlib, json, os, shutil, sqlite3, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_ingest import GH, SID, Ing, line, rec

FX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "providers-v0")
S = "ses_parsekit000001"
PI = "01a1b2c3-0000-7000-8000-0000000000p1"
OC_DDL = """
CREATE TABLE `session` (`id` text PRIMARY KEY, `project_id` text NOT NULL, `parent_id` text, `slug` text NOT NULL, `directory` text NOT NULL, `title` text NOT NULL, `version` text NOT NULL, `share_url` text, `summary_additions` integer, `summary_deletions` integer, `summary_files` integer, `summary_diffs` text, `revert` text, `permission` text, `time_created` integer NOT NULL, `time_updated` integer NOT NULL, `time_compacting` integer, `time_archived` integer, `workspace_id` text, `path` text, `agent` text, `model` text, `cost` real DEFAULT 0 NOT NULL, `tokens_input` integer DEFAULT 0 NOT NULL, `tokens_output` integer DEFAULT 0 NOT NULL, `tokens_reasoning` integer DEFAULT 0 NOT NULL, `tokens_cache_read` integer DEFAULT 0 NOT NULL, `tokens_cache_write` integer DEFAULT 0 NOT NULL, `metadata` text);
CREATE TABLE `message` (`id` text PRIMARY KEY, `session_id` text NOT NULL REFERENCES session(id), `time_created` integer NOT NULL, `time_updated` integer NOT NULL, `data` text NOT NULL);
CREATE TABLE `part` (`id` text PRIMARY KEY, `message_id` text NOT NULL REFERENCES message(id), `session_id` text NOT NULL, `time_created` integer NOT NULL, `time_updated` integer NOT NULL, `data` text NOT NULL);
"""


def jload(*p):
    with open(os.path.join(FX, *p), encoding="utf-8") as g:
        return json.load(g)


def build_db(path, drop=None, extra=None):
    fx = jload("opencode.json")
    if os.path.exists(path):
        os.unlink(path)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")  # like real opencode: a read-only open of a WAL database creates -wal and -shm
    db.executescript(OC_DDL)
    s = fx["session"]
    db.execute("INSERT INTO session(%s) VALUES (%s)" % (",".join(s), ",".join("?" * len(s))), list(s.values()))
    for m in fx["messages"]:
        db.execute("INSERT INTO message VALUES (?,?,?,?,?)", (m["id"], m["session_id"], m["time_created"], m["time_updated"], json.dumps(m["data"])))
    for p in fx["parts"]:
        db.execute("INSERT INTO part VALUES (?,?,?,?,?,?)", (p["id"], p["message_id"], p["session_id"], p["time_created"], p["time_updated"], json.dumps(p["data"])))
    if drop:
        db.execute("DROP TABLE " + drop)
    db.commit()
    db.close()
    return fx


class Prov(Ing):
    def setUp(self):
        super().setUp()
        self.pi = os.path.join(self.tmp, "pi", "sessions")
        self.ocdb = os.path.join(self.tmp, "oc", "opencode.db")
        self.paseo = os.path.join(self.tmp, "paseo-home")
        os.makedirs(os.path.dirname(self.ocdb))
        os.makedirs(os.path.join(self.pi, "--work-parsekit--"))
        self.env.update(AWT_PI_SESSIONS=self.pi, AWT_OPENCODE_DB=self.ocdb, AWT_PASEO_HOME=self.paseo)
        self.db = os.path.join(self.store, "store.db")

    def put_pi(self):
        for f in glob.glob(os.path.join(FX, "pi", "*.jsonl")):
            shutil.copy(f, os.path.join(self.pi, "--work-parsekit--"))
        return os.path.join(self.pi, "--work-parsekit--", os.listdir(os.path.join(self.pi, "--work-parsekit--"))[0])

    def put_paseo(self):
        shutil.copytree(os.path.join(FX, "paseo", "agents"), os.path.join(self.paseo, "agents"))

    def run_src(self, src, *a, root=""):
        return self.ok("ingest", "--source", src, *a, root=root)

    def canon_rows(self, src):
        out = []
        for p in sorted(glob.glob(os.path.join(self.store, "log", src, "**", "*.jsonl"), recursive=True)):
            with open(p, encoding="utf-8") as g:
                out += [json.loads(x) for x in g if x.strip()]
        return out

    def q(self, sql, *args):
        c = sqlite3.connect("file:%s?mode=ro" % self.db, uri=True)
        try:
            return c.execute(sql, args).fetchall()
        finally:
            c.close()

    def digest(self):
        with open(self.db, "rb") as g:
            return hashlib.sha256(g.read()).hexdigest()

    def logical(self):
        """Every table's rows, sorted and without rowids, plus nothing of FTS internals: what an incremental update must share with a rebuild."""
        c = sqlite3.connect("file:%s?mode=ro" % self.db, uri=True)
        try:
            return {t: sorted(map(repr, c.execute("select * from " + t).fetchall())) for (t,) in
                    c.execute("select name from sqlite_master where type='table' and name not like 'fts_%' and name != 'build_state' order by name").fetchall()}
        finally:
            c.close()

    def mk(self, parent, kind, name, *extra):
        r = self.ok("init", "--kind", kind, "--name", name, *extra, root=parent)
        return os.path.join(parent, r.stdout.split()[1])

    def tree(self):
        """root > workspace > task; agent nodes go under the task."""
        self.ok("init", "--kind", "root", root=self.root)
        self.task = self.mk(self.mk(self.root, "workspace", "Alpha"), "task", "Tokenizer", "--goal", "g", "--done", "d")

    def agent_node(self, name, key):
        return self.mk(self.task, "agent", name, "--key", key)


class TestPi(Prov):
    def test_roundtrip_incremental_and_idempotent(self):
        src = self.put_pi()
        with open(src, encoding="utf-8") as g:
            want = [json.loads(x) for x in g]
        r = self.run_src("pi")
        self.assertIn("ingested %d rows from 1 pi files" % len(want), r.stdout)
        got = self.canon_rows("pi")
        self.assertEqual([g["raw"] for g in got], want)
        self.assertEqual({g["src"] for g in got}, {"pi"})
        self.assertEqual([g["seq"] for g in got], list(range(len(want))))
        self.assertTrue(got[0]["src_ref"].endswith(":0"))
        self.assertTrue(glob.glob(os.path.join(self.store, "log", "pi", "2026-10", "*_%s.jsonl" % PI)))
        self.assertIn("0 rows", self.run_src("pi").stdout)
        with open(src, "ab") as g:
            g.write(line({"type": "message", "id": "m8", "parentId": "m7", "timestamp": "2026-10-23T12:40:00.000Z", "message": {"role": "assistant", "content": [{"type": "text", "text": "docs added"}]}}))
        self.assertIn("1 rows", self.run_src("pi").stdout)
        self.assertEqual(len(self.canon_rows("pi")), len(want) + 1)

    def test_secrets_are_flagged_not_redacted(self):
        src = self.put_pi()
        with open(src, "ab") as g:
            g.write(line({"type": "message", "id": "m9", "parentId": "m7", "timestamp": "2026-10-23T12:41:00.000Z", "message": {"role": "user", "content": [{"type": "text", "text": "token " + GH}]}}))
        self.run_src("pi")
        last = self.canon_rows("pi")[-1]
        self.assertGreaterEqual(last["secret_flags"], 1)
        self.assertIn(GH, json.dumps(last["raw"]))

    def test_derivation(self):
        self.put_pi()
        self.init()
        self.run_src("pi", root=self.root)
        self.assertEqual(self.q("select provider_name, conversation_id, cwd, request_model, started_at, ended_at, source, adapter, node_id, join_confidence from sessions"),
                         [("pi", PI, "/work/parsekit", "pi-test-1", "2026-10-23T12:23:19.335Z", "2026-10-23T12:31:02.000Z", "pi", 1, None, None)])
        self.assertEqual(self.q("select seq from turns order by seq"), [(0,), (1,)])
        self.assertEqual(self.q("select role, text, turn_id is not null from messages order by seq"),
                         [("system", "You are a coding agent.", 0), ("user", "add a tokenizer to parsekit", 1), ("assistant", "reading lexer.py", 1), ("toolResult", "def lex(): pass", 1),
                          ("assistant", "tokenizer written", 1), ("toolResult", "1 failed", 1), ("assistant", "fixing the failing zephyr test", 1), ("user", "now add docs", 1), ("assistant", "docs outline ready", 1)])
        self.assertEqual(self.q("select count(*) from messages where turn_id like '%:1'"), [(2,)])
        tc = self.q("select tool_call_id, tool_name, args, result_excerpt, is_error, started_at, ended_at from tool_calls order by tool_call_id")
        self.assertEqual(tc, [("call_a1", "read", '{"path":"lexer.py"}', "def lex(): pass", 0, "2026-10-23T12:23:22.000Z", "2026-10-23T12:23:23.000Z"),
                              ("call_a2", "bash", '{"command":"pytest -q"}', "1 failed", 1, "2026-10-23T12:23:25.000Z", "2026-10-23T12:23:27.000Z")])
        self.assertEqual(self.q("select response_finish_reasons from messages where message_id='m2'"), [('["toolUse"]',)])
        self.assertEqual(self.q("select count(*) from fts_ref where kind='tool_call'"), [(2,)])
        self.assertEqual(self.q("select source, path, errors from ingest_sources")[0][0], "pi")

    def test_missing_dir_and_bad_line(self):
        self.env["AWT_PI_SESSIONS"] = os.path.join(self.tmp, "nope")
        self.assertIn("0 rows", self.run_src("pi").stdout)
        self.env["AWT_PI_SESSIONS"] = self.pi
        src = self.put_pi()
        with open(src, "ab") as g:
            g.write(b"not json\n")
        self.run_src("pi")
        self.assertEqual(self.canon_rows("pi")[-1]["raw"], {"_unparsed": "not json"})


class TestOpencode(Prov):
    def test_rows_and_read_only(self):
        fx = build_db(self.ocdb)
        before = hashlib.sha256(open(self.ocdb, "rb").read()).hexdigest()
        r = self.run_src("opencode")
        self.assertIn("ingested 16 rows from 1 opencode sessions", r.stdout)
        self.assertEqual(hashlib.sha256(open(self.ocdb, "rb").read()).hexdigest(), before)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.ocdb))), ["opencode.db"])
        got = self.canon_rows("opencode")
        self.assertEqual([g["seq"] for g in got], list(range(16)))
        self.assertEqual({g["src"] for g in got}, {"opencode"})
        self.assertEqual([g["session"] for g in got], [S] * 16)
        tables = [g["raw"]["table"] for g in got]
        self.assertEqual((tables.count("session"), tables.count("message"), tables.count("part")), (1, 5, 10))
        p = next(g["raw"] for g in got if g["raw"].get("id") == "prt_05")
        self.assertEqual(p["data"], next(x for x in fx["parts"] if x["id"] == "prt_05")["data"])
        self.assertEqual((p["session_id"], p["message_id"], p["time_created"]), (S, "msg_02", fx["parts"][4]["time_created"]))
        self.assertTrue(glob.glob(os.path.join(self.store, "log", "opencode", "2026-10", S + ".jsonl")))

    def test_incremental_appends_only_changes(self):
        build_db(self.ocdb)
        self.run_src("opencode")
        self.assertIn("0 rows", self.run_src("opencode").stdout)
        c = sqlite3.connect(self.ocdb)
        c.execute("UPDATE part SET time_updated=time_updated+50000, data=? WHERE id='prt_09'", (json.dumps({"type": "text", "text": "now add docs and a changelog"}),))
        c.execute("INSERT INTO message VALUES ('msg_09', ?, 1792758300000, 1792758301000, ?)", (S, json.dumps({"role": "assistant", "time": {"created": 1792758300000}, "modelID": "oc-test-1", "parentID": "msg_04"})))
        c.commit()
        c.close()
        self.assertIn("2 rows", self.run_src("opencode").stdout)
        self.assertIn("0 rows", self.run_src("opencode").stdout)
        self.assertEqual(len(self.canon_rows("opencode")), 18)

    def test_derivation(self):
        build_db(self.ocdb)
        self.init()
        self.run_src("opencode", root=self.root)
        self.assertEqual(self.q("select session_id, provider_name, conversation_id, cwd, request_model, started_at, ended_at, source, node_id from sessions"),
                         [(S, "opencode", S, "/work/parsekit", "oc-test-1", "2026-10-23T12:23:20.000Z", "2026-10-23T12:23:29.000Z", "opencode", None)])
        self.assertEqual(self.q("select seq from turns order by seq"), [(0,), (1,)])
        self.assertEqual(self.q("select message_id, role, text, parent_id, response_finish_reasons from messages order by seq"),
                         [("msg_01", "user", "add a tokenizer to parsekit", None, None), ("msg_02", "assistant", "reading lexer.py", "msg_01", '["tool-calls"]'),
                          ("msg_03", "assistant", "the zephyr test fails", "msg_01", '["stop"]'), ("msg_04", "user", "now add docs", None, None), ("msg_05", "assistant", "docs added", "msg_04", '["stop"]')])
        tc = self.q("select tool_call_id, message_id, tool_name, args, result_excerpt, is_error, started_at, ended_at from tool_calls order by tool_call_id")
        self.assertEqual(tc[0][:6], ("call_o1", "msg_02", "read", '{"filePath":"lexer.py"}', "def lex(): pass", 0))
        self.assertEqual(tc[1][:6], ("call_o2", "msg_03", "bash", '{"command":"pytest -q"}', "1 failed", 1))
        self.assertEqual(tc[0][6:], ("2026-10-23T12:23:21.004Z", "2026-10-23T12:23:21.100Z"))
        self.assertEqual(self.q("select count(*) from messages where text like '%check the lexer%'"), [(0,)])

    def test_updated_part_replaces_the_earlier_row_in_the_store(self):
        build_db(self.ocdb)
        self.run_src("opencode")
        c = sqlite3.connect(self.ocdb)
        c.execute("UPDATE part SET time_updated=time_updated+50000, data=? WHERE id='prt_09'", (json.dumps({"type": "text", "text": "now add docs and a changelog"}),))
        c.commit()
        c.close()
        self.run_src("opencode", root=self.root)
        self.assertEqual(self.q("select text from messages where message_id='msg_04'"), [("now add docs and a changelog",)])

    def test_unknown_schema_is_skipped_with_an_error_not_guessed(self):
        build_db(self.ocdb, drop="part")
        r = self.run_src("opencode")
        self.assertIn("0 rows", r.stdout)
        self.assertIn("1 files failed", r.stdout)
        self.assertEqual(self.canon_rows("opencode"), [])
        with open(os.path.join(self.store, "ingest", "opencode.offsets.json")) as g:
            self.assertIn("part", json.load(g)["errors"]["opencode.db"])
        self.init()
        d = self.awt("doctor", root=self.root)
        self.assertIn("ingest error for opencode.db", d.stdout + d.stderr)

    def test_missing_db_is_not_an_error(self):
        self.assertIn("0 rows", self.run_src("opencode").stdout)

    def test_hook_is_silent(self):
        build_db(self.ocdb)
        r = self.run_src("opencode", "--hook")
        self.assertEqual((r.stdout, r.stderr), ("", ""))
        self.assertEqual(len(self.canon_rows("opencode")), 16)


class TestPaseoJoin(Prov):
    def test_agent_rows_hold_only_the_join_keys(self):
        self.put_paseo()
        r = self.run_src("paseo")
        self.assertIn("ingested 3 rows from 3 paseo files", r.stdout)
        rows = self.canon_rows("paseo")
        self.assertEqual(sorted(g["raw"]["id"] for g in rows), ["agt_cc1", "agt_oc1", "agt_pi1"])
        pi = next(g["raw"] for g in rows if g["raw"]["id"] == "agt_pi1")
        self.assertEqual(pi, {"id": "agt_pi1", "provider": "pi", "sessionId": PI, "cwd": "/work/parsekit", "workspaceId": "ws_parsekit", "createdAt": "2026-10-23T12:23:00.000Z"})
        blob = b"".join(open(p, "rb").read() for p in glob.glob(os.path.join(self.store, "**", "*"), recursive=True) if os.path.isfile(p))
        self.assertNotIn(b"Bearer", blob)
        self.assertIn("0 rows", self.run_src("paseo").stdout)

    def test_paseo_session_id_joins_with_session_id_confidence(self):
        self.put_pi()
        build_db(self.ocdb)
        self.put_paseo()
        self.tree()
        npi = self.agent_node("a-pi", "paseo:agent/agt_pi1")
        self.agent_node("a-oc", "paseo:agent/agt_oc1")
        self.run_src("all", root=self.root)
        self.assertEqual(self.q("select provider_name, node_id, join_confidence from sessions order by provider_name"),
                         [("opencode", "paseo:agent/agt_oc1", "session_id"), ("pi", "paseo:agent/agt_pi1", "session_id")])
        self.assertTrue(os.path.isdir(npi))

    def test_agent_without_a_node_and_unknown_session_stay_unjoined(self):
        self.put_pi()
        self.put_paseo()
        self.tree()
        self.run_src("all", root=self.root)  # no node carries a paseo key; cwd /work/parsekit is no node either
        self.assertEqual(self.q("select node_id, join_confidence from sessions"), [(None, None)])

    def test_cwd_join_is_the_fallback_without_a_paseo_record(self):
        src = self.put_pi()
        with open(src, encoding="utf-8") as g:
            rows = [json.loads(x) for x in g]
        rows[0]["cwd"] = self.root
        with open(src, "w", encoding="utf-8") as g:
            g.writelines(json.dumps(r) + "\n" for r in rows)
        self.tree()
        self.run_src("pi", root=self.root)
        self.assertEqual(self.q("select node_id is not null, join_confidence from sessions"), [(1, "cwd")])

    def test_paseo_join_wins_over_cwd(self):
        src = self.put_pi()
        with open(src, encoding="utf-8") as g:
            rows = [json.loads(x) for x in g]
        rows[0]["cwd"] = self.root
        with open(src, "w", encoding="utf-8") as g:
            g.writelines(json.dumps(r) + "\n" for r in rows)
        self.put_paseo()
        self.tree()
        self.agent_node("a-pi", "paseo:agent/agt_pi1")
        self.run_src("all", root=self.root)
        self.assertEqual(self.q("select node_id, join_confidence from sessions"), [("paseo:agent/agt_pi1", "session_id")])

    def test_claude_sessions_join_by_paseo_id_too(self):
        self.put(self.base_rows())
        self.put_paseo()
        self.tree()
        self.agent_node("a-cc", "paseo:agent/agt_cc1")
        self.run_src("all", root=self.root)
        self.assertEqual(self.q("select provider_name, node_id, join_confidence from sessions"), [("claude_code", "paseo:agent/agt_cc1", "session_id")])


def pipe(*names):
    """The events of the fixture pipe, as the plugin sends them on stdin: all of them, or the ones whose eid starts with a name."""
    with open(os.path.join(FX, "paseo", "events.jsonl"), encoding="utf-8") as g:
        return "".join(x for x in g if not names or any(json.loads(x)["eid"].startswith(n) for n in names))


class TestModels(Prov):
    """MODEL-TRACKING rule 7: a session that switches model mid-session shows two distinct response models, per message and per turn."""

    def test_pi_model_switch(self):
        self.put_pi()
        self.run_src("pi", root=self.root)
        self.assertEqual(self.q("select message_id, response_model from messages where role='assistant' order by seq"),
                         [("m2", "pi-test-1"), ("m4", "pi-test-1"), ("m6", "pi-test-1"), ("m7r", "pi-test-2")])
        self.assertEqual(self.q("select count(*) from messages where role!='assistant' and response_model is not null"), [(0,)])
        self.assertEqual(self.q("select seq, request_model, response_model from turns order by seq"), [(0, "pi-test-1", "pi-test-1"), (1, "pi-test-2", "pi-test-2")])
        self.assertEqual(self.q("select request_model from sessions"), [("pi-test-1",)])
        self.assertEqual(self.q("select count(distinct response_model) from messages"), [(2,)])

    def test_opencode_model_switch(self):
        build_db(self.ocdb)
        self.run_src("opencode", root=self.root)
        self.assertEqual(self.q("select message_id, response_model from messages where role='assistant' order by seq"),
                         [("msg_02", "oc-test-1"), ("msg_03", "oc-test-1"), ("msg_05", "oc-test-2")])
        self.assertEqual(self.q("select seq, request_model, response_model from turns order by seq"), [(0, "oc-test-1", "oc-test-1"), (1, "oc-test-2", "oc-test-2")])
        self.assertEqual(self.q("select request_model from sessions"), [("oc-test-1",)])

    def test_a_pi_switch_without_a_model_change_entry_shows_in_the_response_model(self):
        src = self.put_pi()
        with open(src, encoding="utf-8") as g:
            rows = [json.loads(x) for x in g if json.loads(x).get("id") != "e3"]
        with open(src, "w", encoding="utf-8") as g:
            g.writelines(json.dumps(r) + "\n" for r in rows)
        self.run_src("pi", root=self.root)
        self.assertEqual(self.q("select seq, request_model, response_model from turns order by seq"), [(0, "pi-test-1", "pi-test-1"), (1, "pi-test-1", "pi-test-2")])

    def test_a_transcript_without_a_model_leaves_it_null(self):
        build_db(self.ocdb)
        c = sqlite3.connect(self.ocdb)
        c.execute("UPDATE message SET data=json_remove(data, '$.modelID') WHERE id='msg_05'")
        c.execute("UPDATE message SET data=json_remove(data, '$.model') WHERE id='msg_04'")
        c.commit()
        c.close()
        self.run_src("opencode", root=self.root)
        self.assertEqual(self.q("select response_model from messages where message_id='msg_05'"), [(None,)])
        self.assertEqual(self.q("select request_model, response_model from turns where seq=1"), [(None, None)])


class TestPaseoPipe(Prov):
    def pipe_in(self, text, *a):
        return self.ok("ingest", "--source", "paseo", "--stdin", *a, root=self.root, input=text)

    def setUp(self):
        super().setUp()
        self.put_paseo()
        self.put_pi()
        build_db(self.ocdb)
        self.tree()

    def test_events_land_in_the_agent_file_and_replay_adds_nothing(self):
        r = self.pipe_in(pipe())
        self.assertIn("ingested 10 rows from 10 paseo files", r.stdout)  # 3 agent files + 7 events
        rows = self.canon_rows("paseo")
        ev = [g["raw"] for g in rows if "event" in g["raw"]]
        self.assertEqual(len(ev), 7)
        self.assertEqual(ev[0]["model"], "testprov/oc-test-1")
        self.assertTrue(all(g["src_ref"].startswith(("stdin:", "agents/")) for g in rows))
        self.assertIn("ingested 0 rows", self.pipe_in(pipe()).stdout)
        self.assertEqual(len(self.canon_rows("paseo")), 10)

    def test_unknown_keys_are_dropped_and_bad_lines_are_errors_not_fatal(self):
        bad = json.dumps({"event": "turn", "eid": "turn:x:1", "agentId": "agt_pi1", "outcome": "completed", "headers": {"Authorization": "Bearer x"}}) + "\nnot json\n" + json.dumps({"event": "other", "eid": "e", "agentId": "a"}) + "\n"
        self.pipe_in(bad)
        ev = [g["raw"] for g in self.canon_rows("paseo") if "event" in g["raw"]]
        self.assertEqual(ev, [{"event": "turn", "eid": "turn:x:1", "agentId": "agt_pi1", "outcome": "completed"}])
        with open(os.path.join(self.store, "ingest", "paseo.offsets.json"), encoding="utf-8") as g:
            self.assertIn("stdin", json.load(g)["errors"])
        self.pipe_in(pipe("turn:agt_pi1"))
        with open(os.path.join(self.store, "ingest", "paseo.offsets.json"), encoding="utf-8") as g:
            self.assertNotIn("stdin", json.load(g)["errors"])

    def test_stdin_needs_the_paseo_source(self):
        self.bad("ingest", "--source", "all", "--stdin", root=self.root, input=pipe())
        self.bad("ingest", "--source", "claude", "--stdin", root=self.root, input=pipe())

    def test_turn_outcomes_and_models_are_laid_over_the_transcript_turns(self):
        self.run_src("all", root=self.root)
        self.pipe_in(pipe("turn:"))
        self.assertEqual(self.q("select s.provider_name, t.seq, t.outcome, t.paseo_turn from turns t join sessions s using (session_id) order by 1, 2"),
                         [("opencode", 0, "completed", 1), ("opencode", 1, "failed", 1), ("pi", 0, "completed", 1), ("pi", 1, "canceled", 1)])

    def test_a_transcript_model_wins_and_paseo_fills_a_gap(self):
        c = sqlite3.connect(self.ocdb)
        c.execute("UPDATE message SET data=json_remove(data, '$.model') WHERE id='msg_04'")
        c.execute("UPDATE message SET data=json_remove(data, '$.modelID') WHERE id='msg_05'")
        c.commit()
        c.close()
        self.run_src("all", root=self.root)
        self.pipe_in(pipe("turn:"))
        self.assertEqual(self.q("select t.seq, t.request_model, t.response_model from turns t join sessions s using (session_id) where s.provider_name='opencode' order by 1"),
                         [(0, "oc-test-1", "oc-test-1"), (1, "oc-test-2", None)])

    def test_turns_without_a_session_are_kept_in_the_log_only(self):
        self.pipe_in(pipe("turn:agt_oc1"))  # no opencode ingest: no session to lay them over
        self.assertEqual(self.q("select count(*) from turns"), [(0,)])
        self.assertEqual(self.q("select count(*) from canonical where src='paseo' and json_extract(raw,'$.event')='turn'"), [(2,)])

    def test_permissions_join_request_and_answer(self):
        self.run_src("all", root=self.root)
        self.pipe_in(pipe("perm"))
        self.assertEqual(self.q("select request_id, tool_name, target, decision, decided_by, ts, decided_at from permissions order by request_id"),
                         [("perm-0001", "bash", "pytest -q", "allow", "person", "2026-10-23T12:23:24.000Z", "2026-10-23T12:23:25.000Z"),
                          ("perm-0002", "write", "docs/index.md", "unanswered", None, "2026-10-23T12:23:28.000Z", None)])
        self.assertEqual(self.q("select count(*) from permissions where session_id=?", S), [(2,)])

    def test_an_answer_that_arrives_later_fills_the_row(self):
        self.pipe_in(pipe("perm:"))
        self.assertEqual(self.q("select decision from permissions where request_id='perm-0001'"), [("unanswered",)])
        self.pipe_in(pipe("permres"))
        self.assertEqual(self.q("select decision, decided_by from permissions where request_id='perm-0001'"), [("allow", "person")])

    def rowids(self, provider):
        return self.q("select m.rowid, m.message_id from messages m join sessions s using (session_id) where s.provider_name=? order by 1", provider)

    def test_a_pipe_event_re_derives_no_transcript(self):
        self.run_src("all", root=self.root)
        before = [self.rowids("pi"), self.rowids("opencode")]
        self.pipe_in(pipe())
        self.assertEqual([self.rowids("pi"), self.rowids("opencode")], before)  # same rows, same rowids: nothing was dropped and derived again
        self.assertEqual(self.q("select count(*) from turns where paseo_turn=1"), [(4,)])
        inc = self.logical()
        self.ok("ingest", "--rebuild", root=self.root)
        self.assertEqual(self.logical(), inc)

    def test_a_late_agent_record_re_places_sessions_without_re_deriving_them(self):
        self.run_src("all", root=self.root)
        self.pipe_in(pipe())
        ids = self.rowids("pi")
        self.agent_node("a-pi", "paseo:agent/agt_pi1")
        self.run_src("all", root=self.root)
        self.assertEqual(self.rowids("pi"), ids)
        self.assertEqual(self.q("select node_id, join_confidence from sessions where provider_name='pi'"), [("paseo:agent/agt_pi1", "session_id")])

    def test_a_changed_pi_file_is_re_derived_on_its_own(self):
        src = self.put_pi()
        self.run_src("all", root=self.root)
        self.pipe_in(pipe())
        oc = self.rowids("opencode")
        with open(src, "a", encoding="utf-8") as g:
            g.write(json.dumps({"type": "message", "id": "late01", "parentId": None, "timestamp": "2026-10-23T12:30:00.000Z",
                                "message": {"role": "user", "content": [{"type": "text", "text": "one more"}]}}) + "\n")
        self.run_src("pi", root=self.root)
        self.assertEqual(self.rowids("opencode"), oc)
        self.assertEqual(self.q("select count(*) from messages where message_id='late01'"), [(1,)])
        self.assertEqual(self.q("select count(*) from turns where paseo_turn=1"), [(4,)])  # the Paseo layer was laid over the new turns again
        inc = self.logical()
        self.ok("ingest", "--rebuild", root=self.root)
        self.assertEqual(self.logical(), inc)

    def test_pipe_joins_the_node_and_rebuild_is_byte_stable(self):
        self.agent_node("a-oc", "paseo:agent/agt_oc1")
        self.run_src("all", root=self.root)
        self.pipe_in(pipe())
        self.assertEqual(self.q("select distinct node_id from permissions"), [("paseo:agent/agt_oc1",)])
        inc = self.logical()
        os.unlink(self.ocdb)
        shutil.rmtree(self.paseo)
        self.ok("ingest", "--rebuild", root=self.root)
        self.assertEqual(self.logical(), inc)  # the incremental update and the rebuild hold the same rows
        d1 = self.digest()
        self.ok("ingest", "--rebuild", root=self.root)
        self.assertEqual(self.digest(), d1)


class TestAll(Prov):
    def everything(self):
        self.put(self.base_rows())
        self.put_pi()
        build_db(self.ocdb)
        self.put_paseo()
        self.tree()
        self.agent_node("a-pi", "paseo:agent/agt_pi1")

    def test_all_runs_every_source_and_prints_one_line_each(self):
        self.everything()
        out = self.run_src("all", root=self.root).stdout
        for frag in ("5 rows from 1 claude files", "rows from 1 pi files", "16 rows from 1 opencode sessions", "3 rows from 3 paseo files"):
            self.assertIn(frag, out)
        self.assertEqual(self.q("select provider_name, count(*) from sessions group by 1 order by 1"), [("claude_code", 1), ("opencode", 1), ("pi", 1)])
        self.assertEqual(sorted(r[0] for r in self.q("select distinct source from ingest_sources")), ["claude", "opencode", "paseo", "pi"])

    def test_unknown_source_is_a_usage_error(self):
        self.bad("ingest", "--source", "bogus", root="", code=2)

    def test_rebuild_is_byte_stable_and_never_reads_a_provider(self):
        self.everything()
        self.run_src("all", root=self.root)
        d1 = self.digest()
        os.unlink(self.ocdb)
        shutil.rmtree(self.pi)
        shutil.rmtree(self.paseo)
        shutil.rmtree(self.proj)
        self.ok("ingest", "--rebuild", root=self.root)
        self.assertEqual(self.digest(), d1)

    def test_one_failing_provider_does_not_stop_the_others(self):
        self.everything()
        open(self.ocdb, "wb").write(b"this is not a database" * 50)
        r = self.run_src("all", root=self.root)
        self.assertIn("1 files failed", r.stdout)
        self.assertEqual(self.q("select count(*) from sessions"), [(2,)])

    def test_tool_call_totals(self):
        self.everything()
        self.run_src("all", root=self.root)
        self.assertEqual(self.q("select s.provider_name, count(*) from tool_calls t join sessions s using (session_id) group by 1 order by 1"), [("opencode", 2), ("pi", 2)])


if __name__ == "__main__":
    unittest.main()
