"""usage table and `awt ingest --source ccusage` (SPEC.md, "usage"). Fixtures are fictional: parsekit, fixtures/ccusage-v0."""
import glob, json, os, shutil, stat, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_ingest import CWD, SID, rec
from test_providers import PI, Prov, S, build_db

FX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "ccusage-v0")
COLS = "usage_id, session_id, message_id, turn_id, provider_name, request_model, response_model, usage_input_tokens, usage_output_tokens, cache_read_tokens, cache_write_tokens, cost_usd, cost_source, latency_ms, grain"


def asst(i, text, api, inp, out, model="claude-test-1", cr=0, cw=0, parent=None):
    r = rec("assistant", i, text)
    r["message"].update(id=api, model=model, usage={"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cr, "cache_creation_input_tokens": cw})
    if parent:
        r["parentUuid"] = parent
    return r


class Usage(Prov):
    def setUp(self):
        super().setUp()
        self.init()

    def q(self, sql, *a):
        import sqlite3
        c = sqlite3.connect("file:%s?mode=ro" % self.db, uri=True)
        try:
            return c.execute(sql, a).fetchall()
        finally:
            c.close()

    def ccusage_with(self, sessions):
        """A fake ccusage that prints `sessions` (list of (period, lastActivity, [(model, input)])) and records its arguments in args.txt."""
        d = os.path.join(self.tmp, "bin")
        os.makedirs(d, exist_ok=True)
        data = {"session": [{"agent": "claude", "period": per, "modelBreakdowns": [{"modelName": m, "inputTokens": i, "outputTokens": 0, "cacheCreationTokens": 0, "cacheReadTokens": 0, "cost": i / 1000.0} for m, i in mb],
                             "metadata": {"lastActivity": la}} for per, la, mb in sessions]}
        src = os.path.join(d, "cc.json")
        with open(src, "w") as g:
            json.dump(data, g)
        p = os.path.join(d, "ccusage")
        with open(p, "w") as g:
            g.write("#!/bin/sh\necho \"$@\" > '%s'\ncat '%s'\n" % (os.path.join(d, "args.txt"), src))
        os.chmod(p, 0o755)
        self.env["AWT_CCUSAGE"] = p
        return os.path.join(d, "args.txt")

    def fake_ccusage(self, body=None, code=0):
        d = os.path.join(self.tmp, "bin")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "ccusage")
        src = os.path.join(FX, "session.json")
        with open(p, "w") as g:
            g.write("#!/bin/sh\n[ \"$1 $2\" = \"session --json\" ] || exit 9\n%s\nexit %d\n" % ("cat '%s'" % src if body is None else "printf '%s' '%s'" % ("%s", body), code))
        os.chmod(p, 0o755)
        self.env["AWT_CCUSAGE"] = p
        return p


class TestMessageUsage(Usage):
    def test_claude_streaming_records_make_one_usage_row(self):
        # one API message (id m1) written as two records: the usage is repeated and grows; it counts once, from the last record
        self.put([rec("user", 0, "add a tokenizer"), asst(1, "thinking", "m1", 100, 5, cr=900, cw=50), asst(2, "done", "m1", 100, 40, cr=900, cw=50),
                  rec("user", 3, "now tests"), asst(4, "ok", "m2", 120, 10, model="claude-test-2")])
        self.ok("ingest", "--source", "claude", root=self.root)
        rows = self.q("select %s from usage order by message_id" % COLS)
        self.assertEqual(rows, [
            ("m:%s:u-2" % SID, SID, "u-2", SID + ":0", "claude_code", "claude-test-1", "claude-test-1", 100, 40, 900, 50, None, None, 120000, "message"),
            ("m:%s:u-4" % SID, SID, "u-4", SID + ":1", "claude_code", "claude-test-2", "claude-test-2", 120, 10, 0, 0, None, None, 60000, "message")])
        # joins by message id to messages and turns
        j = self.q("select m.role, t.seq from usage u join messages m on m.session_id=u.session_id and m.message_id=u.message_id join turns t on t.turn_id=u.turn_id order by t.seq")
        self.assertEqual(j, [("assistant", 0), ("assistant", 1)])

    def test_pi_and_opencode_cost_is_computed_from_the_transcript(self):
        self.put_pi()
        build_db(self.ocdb)
        self.ok("ingest", "--source", "all", root=self.root)
        rows = self.q("select provider_name, response_model, usage_input_tokens, usage_output_tokens, cost_usd, cost_source, latency_ms from usage where provider_name in ('pi','opencode') order by provider_name, message_id")
        self.assertIn(("pi", "pi-test-1", 10, 5, 0.001, "computed", 2000), rows)
        self.assertIn(("opencode", "oc-test-1", 10, 5, 0.004, "computed", 500), rows)

    def test_user_messages_have_no_usage_and_no_usage_is_no_row(self):
        self.put([rec("user", 0, "hi"), {**rec("assistant", 1, "x"), "message": {"role": "assistant", "content": [], "model": "claude-test-1"}}])
        self.ok("ingest", "--source", "claude", root=self.root)
        self.assertEqual(self.q("select count(*) from usage"), [(0,)])


SID2 = "5e5e5e5e-0000-4000-8000-00000000cccc"


def sess(rows, sid):
    return [dict(r, sessionId=sid) for r in rows]


class TestNoDoubleCount(Usage):
    """Review H1/M9/M1: a parent, a subagent file (same sessionId) and a resumed file that repeats the parent's first message. The true input total is 100 + 1000 + 7."""
    def build(self):
        parent = [rec("user", 0, "add a tokenizer"), asst(1, "done", "m1", 100, 0)]
        self.put(parent)
        self.put(sess([rec("user", 0, "sub task"), asst(1, "sub done", "s1", 1000, 0)], SID), path=self.src(sub="agent-x"))
        # the resumed file copies the parent's records (old sessionId, same message id), then goes on under its own id
        self.put(parent + sess([rec("user", 2, "go on"), asst(3, "more", "m9", 7, 0)], SID2), path=self.src(SID2))
        self.ok("ingest", "--source", "claude", root=self.root)

    def total(self):
        return self.q("select sum(usage_input_tokens) from usage_best")[0][0]

    def test_without_ccusage_a_copied_message_counts_once(self):
        self.build()
        self.assertEqual(self.total(), 1107)

    def test_a_resumed_file_is_its_own_conversation_and_a_subagent_keeps_the_parent(self):
        self.build()
        self.assertEqual(self.q("select session_id, conversation_id from sessions order by session_id"), [(SID, SID), (SID + ".agent-x", SID), (SID2, SID2)])

    def test_with_ccusage_every_session_of_a_conversation_is_covered_once(self):
        self.build()
        self.ccusage_with([(SID, "2026-10-03T10:00:00.000Z", [("claude-test-1", 1100)]), (SID2, "2026-10-03T10:00:00.000Z", [("claude-test-1", 7)])])
        self.ok("ingest", "--source", "ccusage", root=self.root)
        self.assertEqual(self.total(), 1107)
        self.assertEqual(self.q("select count(*) from usage_best where cost_source='ccusage'"), [(2,)])

    def test_stale_ccusage_loses_to_newer_message_rows(self):
        self.build()  # the last billed message is u-3 at 09:03
        self.ccusage_with([(SID, "2026-10-03T09:00:30.000Z", [("claude-test-1", 1100)]), (SID2, "2026-10-03T10:00:00.000Z", [("claude-test-1", 7)])])
        self.ok("ingest", "--source", "ccusage", root=self.root)
        # SID's row ends before SID's own messages (09:01), so its messages count; SID2's row covers SID2
        self.assertEqual(self.total(), 1107)
        self.ccusage_with([(SID, "2026-10-03T09:00:30.000Z", [("claude-test-1", 1100)]), (SID2, "2026-10-03T09:00:30.000Z", [("claude-test-1", 7)])])
        self.ok("ingest", "--source", "ccusage", root=self.root)
        self.assertEqual(self.q("select count(*) from usage_best where cost_source='ccusage'"), [(0,)])
        self.assertEqual(self.total(), 1107)

    def test_ccusage_runs_offline(self):
        self.build()
        args = self.ccusage_with([(SID, "2026-10-03T10:00:00.000Z", [("claude-test-1", 1100)])])
        self.ok("ingest", "--source", "ccusage", root=self.root)
        with open(args) as g:
            self.assertEqual(g.read().split(), ["session", "--json", "--offline"])


class TestPiBranchUsage(Usage):
    def test_abandoned_branch_spend_is_kept_but_charged_to_no_turn(self):
        d = os.path.join(self.pi, "--work-parsekit--")
        src = glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", "providers-v0", "pi-branch", "*.jsonl"))[0]
        with open(src) as g:
            rows = [json.loads(x) for x in g if x.strip()]
        for r in rows:
            if r.get("id") in ("m2", "m6"):
                r["message"]["usage"] = {"input": 11, "output": 1, "cacheRead": 0, "cacheWrite": 0, "cost": {"total": 0.001}}
        with open(os.path.join(d, os.path.basename(src)), "w") as g:
            g.write("".join(json.dumps(r) + "\n" for r in rows))
        self.ok("ingest", "--source", "pi", root=self.root)
        self.assertEqual(self.q("select message_id, turn_id is null, usage_input_tokens from usage order by message_id"), [("m2", 0, 11), ("m6", 1, 11)])
        self.assertEqual(self.q("select sum(usage_input_tokens) from usage_best"), [(22,)])


class TestCcusage(Usage):
    def setUp(self):
        super().setUp()
        self.put([rec("user", 0, "add a tokenizer"), asst(1, "done", "m1", 100, 40, cr=900, cw=50)])
        self.put_pi()

    def test_import_rows_join_sessions_and_rebuild_is_identical(self):
        self.fake_ccusage()
        self.ok("ingest", "--source", "claude", root=self.root)
        self.ok("ingest", "--source", "pi", root=self.root)
        r = self.ok("ingest", "--source", "ccusage", root=self.root)
        self.assertIn("ingested 3 rows from 3 ccusage sessions", r.stdout)
        rows = self.q("select usage_id, session_id, conversation_id, provider_name, response_model, usage_input_tokens, usage_output_tokens, cache_read_tokens, cache_write_tokens, cost_usd, cost_source, message_id from usage where grain='session_model' order by usage_id")
        self.assertEqual(len(rows), 4)
        by = {(x[2], x[4]): x for x in rows}
        a = by[(SID, "claude-test-1")]
        self.assertEqual((a[1], a[3], a[5:11]), (SID, "claude_code", (600, 300, 2000, 100, 0.03, "ccusage")))
        self.assertIsNone(a[11])
        self.assertTrue(by[(PI, "pi-test-1")][1])  # joined to the pi session
        self.assertIsNone(by[("9a9a9a9a-0000-4000-8000-00000000bbbb", "claude-test-1")][1])  # not ingested here: kept, unjoined
        # canonical rows exist, so a rebuild gives the same table
        before = self.q("select * from usage order by usage_id")
        self.ok("ingest", "--rebuild", root=self.root)
        self.assertEqual(self.q("select * from usage order by usage_id"), before)
        self.assertIn("0 rows", self.ok("ingest", "--source", "ccusage", root=self.root).stdout)

    def test_changed_session_is_appended_and_the_last_wins(self):
        self.fake_ccusage()
        self.ok("ingest", "--source", "ccusage", root=self.root)
        with open(os.path.join(FX, "session.json")) as g:
            d = json.load(g)
        d["session"][2]["modelBreakdowns"][0]["cost"] = 0.5
        p = os.path.join(self.tmp, "changed.json")
        with open(p, "w") as g:
            json.dump(d, g)
        self.fake_ccusage(body=None)
        with open(self.env["AWT_CCUSAGE"], "w") as g:
            g.write("#!/bin/sh\ncat '%s'\n" % p)
        self.ok("ingest", "--source", "ccusage", root=self.root)
        self.assertEqual(self.q("select cost_usd from usage where conversation_id='9a9a9a9a-0000-4000-8000-00000000bbbb'"), [(0.5,)])

    def test_missing_ccusage_fails_gracefully_and_changes_nothing(self):
        self.env["AWT_CCUSAGE"] = os.path.join(self.tmp, "no-such-ccusage")
        r = self.awt("ingest", "--source", "ccusage", root=self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("ccusage", r.stderr)
        self.assertIn("npm", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertFalse(os.path.isdir(os.path.join(self.store, "log", "ccusage")))

    def test_bad_output_is_refused(self):
        p = self.fake_ccusage()
        with open(p, "w") as g:
            g.write("#!/bin/sh\necho 'not json'\n")
        r = self.awt("ingest", "--source", "ccusage", root=self.root)
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)
        self.fake_ccusage(code=3)
        r = self.awt("ingest", "--source", "ccusage", root=self.root)
        self.assertEqual(r.returncode, 1)

    def test_all_skips_ccusage(self):
        self.env["AWT_CCUSAGE"] = os.path.join(self.tmp, "no-such-ccusage")
        r = self.ok("ingest", "--source", "all", root=self.root)
        self.assertNotIn("ccusage", r.stdout)

    def test_best_cost_view_prefers_ccusage_without_double_counting(self):
        self.fake_ccusage()
        self.ok("ingest", "--source", "claude", root=self.root)
        self.ok("ingest", "--source", "ccusage", root=self.root)
        rows = self.q("select session_id, response_model, usage_input_tokens, cost_usd, cost_source from usage_best where session_id=? order by response_model", SID)
        self.assertEqual(rows, [(SID, "claude-test-1", 600, 0.03, "ccusage"), (SID, "claude-test-2", 400, 0.0125, "ccusage")])


if __name__ == "__main__":
    unittest.main()
