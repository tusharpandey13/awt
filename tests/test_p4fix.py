"""Phase 4 review fixes (H1, M1-M6, lows). Fixtures are hand-made in the fictional parsekit project."""
import glob, json, os, shutil, sqlite3, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_providers import FX, S, Prov, build_db, pipe


def pi_entries(sid, turns, extra=()):
    """A pi session: header, then per (user ts, assistant ts) a user and an assistant message in one chain."""
    rows = [{"type": "session", "version": 3, "id": sid, "timestamp": "2026-10-24T12:00:00.000Z", "cwd": "/work/parsekit"}]
    parent = None
    for i, (u, a) in enumerate(turns):
        rows.append({"type": "message", "id": "u%d" % i, "parentId": parent, "timestamp": u, "message": {"role": "user", "content": [{"type": "text", "text": "ask %d" % i}]}})
        rows.append({"type": "message", "id": "a%d" % i, "parentId": "u%d" % i, "timestamp": a, "message": {"role": "assistant", "model": "pi-test-1", "content": [{"type": "text", "text": "answer %d" % i}], "stopReason": "stop"}})
        parent = "a%d" % i
    return rows + list(extra)


class P4(Prov):
    def put_rows(self, name, rows):
        p = os.path.join(self.pi, "--work-parsekit--", name)
        with open(p, "w", encoding="utf-8") as g:
            g.writelines(json.dumps(r) + "\n" for r in rows)
        return p

    def put_agent(self, aid, provider, sid, handle=None):
        d = os.path.join(self.paseo, "agents", "tmp-parsekit")
        os.makedirs(d, exist_ok=True)
        a = {"id": aid, "provider": provider, "cwd": "/work/parsekit", "workspaceId": "ws_parsekit", "createdAt": "2026-10-24T11:59:00.000Z", "persistence": {"provider": provider, "sessionId": sid}}
        if handle:
            a["persistence"]["nativeHandle"] = handle
        with open(os.path.join(d, aid + ".json"), "w", encoding="utf-8") as g:
            json.dump(a, g)

    def pipe_in(self, text, *a):
        return self.ok("ingest", "--source", "paseo", "--stdin", *a, root=self.root, input=text)

    def errors(self, src):
        with open(os.path.join(self.store, "ingest", src + ".offsets.json"), encoding="utf-8") as g:
            return json.load(g)["errors"]


def turn_ev(aid, n, start, outcome, **kw):
    return json.dumps(dict(event="turn", eid="turn:%s:%s" % (aid, n), agentId=aid, turnId=n, startedAt=start, endedAt=start, outcome=outcome, **kw)) + "\n"


class TestH1(P4):
    def test_two_turns_less_than_5s_apart_keep_their_own_outcomes(self):
        sid = "pi-fast-0001"
        self.put_rows("2026-10-24T12-00-00-000Z_%s.jsonl" % sid, pi_entries(sid, [("2026-10-24T12:00:00.300Z", "2026-10-24T12:00:01.000Z"), ("2026-10-24T12:00:02.300Z", "2026-10-24T12:00:03.000Z")]))
        self.put_agent("agt_fast", "pi", sid)
        self.run_src("all", root=self.root)
        self.pipe_in(turn_ev("agt_fast", "t1", "2026-10-24T12:00:00.000Z", "completed") + turn_ev("agt_fast", "t2", "2026-10-24T12:00:02.000Z", "failed"))
        want = [(0, "completed", 1), (1, "failed", 1)]
        self.assertEqual(self.q("select seq, outcome, paseo_turn from turns order by seq"), want)
        inc = self.logical()
        self.ok("ingest", "--rebuild", root=self.root)
        self.assertEqual(self.q("select seq, outcome, paseo_turn from turns order by seq"), want)
        self.assertEqual(self.logical(), inc)


class TestM1(P4):
    def test_reading_a_wal_database_creates_no_wal_or_shm(self):
        build_db(self.ocdb)
        with open(self.ocdb, "rb") as g:
            self.assertEqual(g.read(20)[18:20], b"\x02\x02")  # header file-format versions 2 = WAL mode
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.ocdb))), ["opencode.db"])
        self.run_src("opencode", root=self.root)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.ocdb))), ["opencode.db"])
        self.assertEqual(self.q("select count(*) from messages"), [(5,)])


class TestM2(P4):
    def test_a_non_string_event_is_a_bad_line_not_a_failed_batch(self):
        self.put_agent("agt_x", "pi", "s")
        bad = '{"event":{"a":1},"eid":"e","agentId":"agt_x"}\n{"event":["turn"],"eid":"e","agentId":"agt_x"}\n[1]\n'
        self.pipe_in(bad + turn_ev("agt_x", "t9", "2026-10-24T12:00:00.000Z", "completed"))
        ev = [g["raw"]["eid"] for g in self.canon_rows("paseo") if "event" in g["raw"]]
        self.assertEqual(ev, ["turn:agt_x:t9"])
        self.assertIn("stdin", self.errors("paseo"))


class TestL3(P4):
    def test_a_deleted_paseo_file_unjoins_its_sessions_like_a_rebuild(self):
        sid = "pi-gone-0001"
        self.put_rows("2026-10-24T12-00-00-000Z_%s.jsonl" % sid, pi_entries(sid, [("2026-10-24T12:00:00.300Z", "2026-10-24T12:00:01.000Z")]))
        self.put_agent("agt_gone", "pi", sid)
        self.tree()
        self.agent_node("a-gone", "paseo:agent/agt_gone")
        self.run_src("all", root=self.root)
        self.assertEqual(self.q("select node_id, join_confidence from sessions"), [("paseo:agent/agt_gone", "session_id")])
        os.unlink(glob.glob(os.path.join(self.store, "log", "paseo", "agt_gone.jsonl"))[0])
        self.run_src("pi", root=self.root)
        self.assertEqual(self.q("select node_id, join_confidence from sessions"), [(None, None)])
        inc = self.logical()
        self.ok("ingest", "--rebuild", root=self.root)
        self.assertEqual(self.logical(), inc)


class TestL2(P4):
    def test_paseo_model_is_normalised_and_default_is_never_filled(self):
        sid = "pi-model-0001"
        rows = pi_entries(sid, [("2026-10-24T12:00:00.300Z", "2026-10-24T12:00:01.000Z"), ("2026-10-24T12:01:00.300Z", "2026-10-24T12:01:01.000Z")])
        for r in rows:  # no model anywhere in the transcript
            if r["type"] == "message" and r["message"]["role"] == "assistant":
                del r["message"]["model"]
        self.put_rows("2026-10-24T12-00-00-000Z_%s.jsonl" % sid, rows)
        self.put_agent("agt_m", "pi", sid)
        self.run_src("all", root=self.root)
        self.pipe_in(turn_ev("agt_m", "t1", "2026-10-24T12:00:00.000Z", "completed", model="testprov/pi-test-9") + turn_ev("agt_m", "t2", "2026-10-24T12:01:00.000Z", "completed", model="pi:default"))
        self.assertEqual(self.q("select seq, request_model, paseo_turn from turns order by seq"), [(0, "pi-test-9", 1), (1, None, 1)])
        self.assertEqual(self.q("select count(*) from canonical where raw like '%pi:default%'"), [(1,)])  # kept in canonical


class TestM6(P4):
    def hits(self, word):
        return self.q("select count(*) from fts_text where fts_text match ?", word)[0][0]

    def delete(self, sql_where):
        c = sqlite3.connect(self.ocdb)
        for t, w in sql_where:
            c.execute("DELETE FROM %s WHERE %s" % (t, w))
        c.commit()
        c.close()

    def test_a_reverted_message_leaves_the_store_but_stays_in_the_canonical_file(self):
        build_db(self.ocdb)
        self.run_src("opencode", root=self.root)
        self.assertEqual((self.hits("zephyr"), self.q("select count(*) from messages")), (1, [(5,)]))
        self.delete([("part", "message_id='msg_03'"), ("message", "id='msg_03'")])
        r = self.run_src("opencode", root=self.root)
        self.assertEqual(self.q("select count(*) from messages where message_id='msg_03'"), [(0,)])
        self.assertEqual(self.q("select count(*) from tool_calls where message_id='msg_03'"), [(0,)])
        self.assertEqual(self.hits("zephyr"), 0)
        got = self.canon_rows("opencode")
        self.assertEqual(len([g for g in got if g["raw"].get("id") == "msg_03"]), 2)  # the old row and its tombstone
        self.assertTrue([g for g in got if g["raw"].get("id") == "msg_03"][-1]["raw"]["deleted"])
        self.assertIn("rows from 1 opencode", r.stdout)
        inc = self.logical()
        self.ok("ingest", "--rebuild", root=self.root)
        self.assertEqual(self.logical(), inc)
        self.assertIn("0 rows", self.run_src("opencode", root=self.root).stdout)  # nothing more to append

    def test_a_deleted_session_leaves_the_store(self):
        build_db(self.ocdb)
        self.run_src("opencode", root=self.root)
        self.delete([("part", "session_id='%s'" % S), ("message", "session_id='%s'" % S), ("session", "id='%s'" % S)])
        self.run_src("opencode", root=self.root)
        self.assertEqual(self.q("select (select count(*) from sessions), (select count(*) from messages), (select count(*) from tool_calls), (select count(*) from turns)"), [(0, 0, 0, 0)])
        self.assertEqual(self.hits("zephyr"), 0)
        self.assertEqual(len(self.canon_rows("opencode")), 16 + 16)
        inc = self.logical()
        self.ok("ingest", "--rebuild", root=self.root)
        self.assertEqual(self.logical(), inc)

    def test_a_row_that_comes_back_is_live_again(self):
        build_db(self.ocdb)
        self.run_src("opencode", root=self.root)
        self.delete([("part", "message_id='msg_05'"), ("message", "id='msg_05'")])
        self.run_src("opencode", root=self.root)
        self.assertEqual(self.q("select count(*) from messages"), [(4,)])
        fx = json.load(open(os.path.join(FX, "opencode.json")))
        c = sqlite3.connect(self.ocdb)
        for m in fx["messages"]:
            if m["id"] == "msg_05":
                c.execute("INSERT INTO message VALUES (?,?,?,?,?)", (m["id"], m["session_id"], m["time_created"], m["time_updated"], json.dumps(m["data"])))
        c.commit()
        c.close()
        self.run_src("opencode", root=self.root)
        self.assertEqual(self.q("select count(*) from messages"), [(5,)])


class TestM4(P4):
    def setUp(self):
        super().setUp()
        for k in ("PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR"):
            self.env.pop(k, None)

    def session(self, dirpath, sid, name=None):
        os.makedirs(dirpath, exist_ok=True)
        p = os.path.join(dirpath, name or "2026-10-24T12-00-00-000Z_%s.jsonl" % sid)
        with open(p, "w", encoding="utf-8") as g:
            g.writelines(json.dumps(r) + "\n" for r in pi_entries(sid, [("2026-10-24T12:00:00.300Z", "2026-10-24T12:00:01.000Z")]))
        return p

    def sids(self):
        return [r[0] for r in self.q("select conversation_id from sessions order by 1")]

    def test_session_dir_env_and_agent_dir_settings(self):
        agent = os.path.join(self.tmp, "agent")
        del self.env["AWT_PI_SESSIONS"]
        self.env["PI_CODING_AGENT_DIR"] = agent
        self.session(os.path.join(agent, "sessions", "--p--"), "pi-default-01")
        self.run_src("pi", root=self.root)
        self.assertEqual(self.sids(), ["pi-default-01"])
        self.env["PI_CODING_AGENT_SESSION_DIR"] = os.path.join(self.tmp, "envdir")
        self.session(os.path.join(self.tmp, "envdir", "--p--"), "pi-env-01")
        self.run_src("pi", root=self.root)
        self.assertEqual(self.sids(), ["pi-default-01", "pi-env-01"])  # a session already stored stays; the new location is read too
        with open(os.path.join(agent, "settings.json"), "w") as g:
            json.dump({"sessionDir": "custom-sessions"}, g)  # relative to the agent dir
        self.session(os.path.join(agent, "custom-sessions"), "pi-settings-01")
        self.run_src("pi", root=self.root)
        self.assertEqual(self.sids(), ["pi-default-01", "pi-env-01", "pi-settings-01"])

    def test_paseo_native_handle_path_and_project_settings(self):
        f = self.session(os.path.join(self.tmp, "elsewhere"), "pi-handle-01")
        self.put_agent("agt_h", "pi", "pi-handle-01", handle=f)
        proj = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(proj, ".pi"))
        with open(os.path.join(proj, ".pi", "settings.json"), "w") as g:
            json.dump({"sessionDir": os.path.join(self.tmp, "projsessions")}, g)
        self.session(os.path.join(self.tmp, "projsessions"), "pi-proj-01")
        d = os.path.join(self.paseo, "agents", "tmp-parsekit")
        with open(os.path.join(d, "agt_p.json"), "w") as g:
            json.dump({"id": "agt_p", "provider": "pi", "cwd": proj, "persistence": {"sessionId": "pi-proj-01", "nativeHandle": "pi-proj-01"}}, g)
        self.run_src("all", root=self.root)
        self.assertEqual(self.sids(), ["pi-handle-01", "pi-proj-01"])
        n = len(self.canon_rows("pi"))
        self.assertIn("0 rows from", self.run_src("pi", root=self.root).stdout)  # incremental: nothing twice
        self.assertEqual(len(self.canon_rows("pi")), n)
        with open(f, "a", encoding="utf-8") as g:
            g.write(json.dumps({"type": "message", "id": "late", "parentId": "a0", "timestamp": "2026-10-24T12:05:00.000Z", "message": {"role": "user", "content": [{"type": "text", "text": "more"}]}}) + "\n")
        self.run_src("pi", root=self.root)
        self.assertEqual(len(self.canon_rows("pi")), n + 1)


class TestM5(P4):
    def put_branch(self):
        for f in glob.glob(os.path.join(FX, "pi-branch", "*.jsonl")):
            shutil.copy(f, os.path.join(self.pi, "--work-parsekit--"))

    def test_the_active_branch_is_the_conversation_and_the_rest_is_marked(self):
        self.put_branch()
        self.run_src("pi", root=self.root)
        self.assertEqual(self.q("select message_id, active, turn_id is null from messages order by seq"),
                         [("m1", 1, 0), ("m2", 1, 0), ("m3", 1, 0), ("m4", 1, 0), ("m5", 0, 1), ("m6", 0, 1), ("m7", 1, 0), ("m8", 1, 0), ("m9", 1, 0), ("m10", 1, 0)])
        self.assertEqual(self.q("select seq, started_at from turns order by seq"), [(0, "2026-10-24T13:00:10.000Z"), (1, "2026-10-24T13:01:00.000Z"), (2, "2026-10-24T13:01:30.000Z")])
        self.assertEqual(self.q("select m.message_id from messages m join turns t using (turn_id) where t.seq=1 order by m.seq"), [("m7",), ("m8",)])
        # the abandoned branch's model change and model do not leak into the session or the turns
        self.assertEqual(self.q("select request_model from sessions"), [("pi-test-1",)])
        self.assertEqual(self.q("select distinct request_model, response_model from turns"), [("pi-test-1", "pi-test-1")])
        self.assertEqual(self.q("select response_model from messages where message_id='m6'"), [("pi-test-9",)])  # kept as it was written
        self.assertEqual(self.q("select count(*) from fts_text where fts_text match 'regex'"), [(2,)])  # still searchable

    def test_context_edits_are_applied_to_the_text_and_the_index(self):
        self.put_branch()
        self.run_src("pi", root=self.root)
        self.assertEqual(self.q("select text from messages where message_id in ('m4','m8') order by seq"), [("",), ("scanner condensed",)])
        self.assertEqual(self.q("select count(*) from fts_text where fts_text match 'verbose'"), [(0,)])
        self.assertEqual(self.q("select count(*) from fts_text where fts_text match 'condensed'"), [(1,)])
        self.assertEqual(self.q("select count(*) from fts_text where fts_text match 'table'"), [(0,)])
        self.assertEqual(self.q("select count(*) from canonical where raw like '%verbose%'"), [(1,)])  # the original stays in canonical
        self.assertEqual(self.q("select count(*) from tool_calls"), [(1,)])  # an edit changes what the model saw, not what was done

    def test_incremental_equals_rebuild_and_a_branch_arriving_later_re_derives(self):
        src = os.path.join(FX, "pi-branch")
        f = glob.glob(os.path.join(src, "*.jsonl"))[0]
        with open(f, encoding="utf-8") as g:
            lines = g.readlines()
        dst = os.path.join(self.pi, "--work-parsekit--", os.path.basename(f))
        with open(dst, "w", encoding="utf-8") as g:
            g.writelines(lines[:9])  # up to m6: the conversation is still one line
        self.run_src("pi", root=self.root)
        self.assertEqual(self.q("select count(*) from messages where active=0"), [(0,)])  # the last entry is m6
        with open(dst, "a", encoding="utf-8") as g:
            g.writelines(lines[9:])
        self.run_src("pi", root=self.root)
        self.assertEqual(self.q("select count(*) from messages where active=0"), [(2,)])
        inc = self.logical()
        self.ok("ingest", "--rebuild", root=self.root)
        self.assertEqual(self.logical(), inc)


if __name__ == "__main__":
    unittest.main()
