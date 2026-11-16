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


if __name__ == "__main__":
    unittest.main()
