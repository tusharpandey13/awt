"""Model tracking (SPEC.md, "Model tracking"): every record names the model that produced it. Fictional parsekit data in temp dirs."""
import json, os, sqlite3, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_awt import Base
from test_ingest import Ing, rec, SID
from test_store import Store


class TestCli(Base):
    def setUp(self):
        super().setUp()
        self.env.pop("AWT_MODEL", None)
        self.init()

    def last(self, typ):
        return self.rows(typ)[-1]["model"]

    def test_unset_is_unknown_unset(self):  # rule 1: never fails for lack of a model
        self.ok("note", "a fact")
        self.assertEqual(self.last("note"), "unknown:unset")
        self.assertEqual(self.rows("task")[0]["model"], "unknown:unset")

    def test_env_beats_unset_and_flag_beats_env(self):
        env = dict(self.env, AWT_MODEL="claude-sonnet-5-5")
        self.ok("note", "from env", env=env)
        self.assertEqual(self.last("note"), "claude-sonnet-5-5")
        self.ok("note", "from flag", "--model", "claude-opus-5-5", env=env)
        self.assertEqual(self.last("note"), "claude-opus-5-5")
        self.ok("--model=m-eq", "note", "equals form")
        self.assertEqual(self.last("note"), "m-eq")

    def test_empty_model_falls_through(self):
        self.ok("note", "blank", env=dict(self.env, AWT_MODEL="  "))
        self.assertEqual(self.last("note"), "unknown:unset")

    def test_every_write_verb_stamps_a_model(self):
        m = ["--model", "claude-sonnet-5-5"]
        self.ok("decide", "retry with jitter", "--why", "sync", *m)
        self.ok("ask", "hard limit?", *m)
        self.ok("ref", "https://example.com/p", "--title", "doc", *m)
        self.ok("state", "--now", "n", "--next", "x", *m)
        eid = self.ok("effect", "plan", "--target", "slack:#eng", *m).stdout.split()[0]
        self.ok("effect", "begin", eid, *m)
        self.ok("effect", "mark", eid, "sent", *m)
        self.ok("status", "paused", *m)
        for r in self.rows():
            if r["ts"] and r["type"] != "task":
                self.assertEqual(r["model"], "claude-sonnet-5-5", r)

    def test_person_gets_unset_unless_flagged(self):
        env = dict(self.env, AWT_MODEL="claude-sonnet-5-5")
        self.ok("--by", "person", "note", "by hand", env=dict(env))
        # AWT_MODEL belongs to an agent env: a person row only takes the explicit flag
        self.assertEqual(self.last("note"), "unknown:unset")
        self.ok("--by", "person", "note", "by hand 2", "--model", "claude-opus-5-5", env=env)
        self.assertEqual(self.last("note"), "claude-opus-5-5")

    def test_legacy_rows_read_as_unknown_legacy_and_are_not_rewritten(self):  # rule 2
        self.raw_append(dict(type="note", id="n-00000001", text="old note"))
        before = self.events()
        out = json.loads(self.ok("list", "notes", "--json").stdout)
        old = [n for n in out if n["id"] == "n-00000001"][0]
        self.assertEqual(old["model"], "unknown:legacy")
        self.ok("list")
        self.assertEqual(self.events(), before)

    def test_effect_show_prints_the_model(self):  # rule 8
        eid = self.plan("--model", "claude-sonnet-5-5")
        self.assertIn("model: claude-sonnet-5-5", self.ok("effect", "show", eid).stdout)

    def test_doctor_counts_unknown_models_as_a_warning(self):  # rule 8
        self.ok("note", "one")
        self.raw_append(dict(type="note", id="n-00000002", text="legacy"))
        self.ok("note", "named", "--model", "claude-sonnet-5-5")
        r = self.ok("doctor")
        line = [x for x in r.stdout.splitlines() if "unknown model" in x]
        self.assertEqual(len(line), 1, r.stdout)
        self.assertTrue(line[0].startswith("warn"), line)
        self.assertRegex(line[0], r"\b3\b")  # task row + note (unset) + legacy note


class TestDoctorOk(Base):
    def test_doctor_is_ok_when_every_row_names_a_model(self):
        env = dict(self.env, AWT_MODEL="claude-sonnet-5-5")
        self.ok("init", "--goal", "g", "--done", "d", env=env)
        self.ok("note", "x", env=env)
        r = self.ok("doctor", env=env)
        self.assertIn("ok every row names a model", r.stdout)


class TestStore(Store):
    def setUp(self):
        super().setUp()
        self.env.pop("AWT_MODEL", None)

    def asst(self, i, text, model):
        r = rec("assistant", i, text)
        r["message"]["model"] = model
        return r

    def switching(self):
        return [rec("user", 0, "add a tokenizer to parsekit"),
                self.asst(1, "reading lexer.py", "claude-sonnet-5-5"),
                rec("user", 2, "now add tests"),
                self.asst(3, "writing tests", "claude-opus-5-5"),
                rec("user", 4, "ship it"),
                self.asst(5, "done", "claude-opus-5-5")]

    def test_schema_has_model_columns_not_null(self):
        self.build(self.switching())
        info = {r[1]: r for r in self.q("PRAGMA table_info(records)")}
        self.assertEqual(info["model"][3], 1)
        for col in ("session_id", "turn_id"):
            self.assertIn(col, info)
        self.assertIn("request_model", [r[1] for r in self.q("PRAGMA table_info(turns)")])
        self.assertIn("response_model", [r[1] for r in self.q("PRAGMA table_info(turns)")])
        self.assertIn("response_model", [r[1] for r in self.q("PRAGMA table_info(messages)")])

    def test_mid_session_switch_gives_two_response_models(self):  # rule 9
        self.build(self.switching())
        got = self.q("SELECT DISTINCT response_model FROM messages WHERE response_model IS NOT NULL ORDER BY 1")
        self.assertEqual(got, [("claude-opus-5-5",), ("claude-sonnet-5-5",)])
        self.assertEqual(self.q("SELECT count(*) FROM messages WHERE role='user' AND response_model IS NOT NULL"), [(0,)])
        self.assertEqual(self.q("SELECT request_model FROM sessions"), [("claude-sonnet-5-5",)])

    def test_turn_models(self):
        self.build(self.switching())
        self.assertEqual(self.q("SELECT seq, request_model, response_model FROM turns ORDER BY seq"),
                         [(0, "claude-sonnet-5-5", "claude-sonnet-5-5"), (1, "claude-opus-5-5", "claude-opus-5-5"), (2, "claude-opus-5-5", "claude-opus-5-5")])

    def test_turn_that_switches_inside(self):
        rows = [rec("user", 0, "go"), self.asst(1, "a", "claude-sonnet-5-5"), self.asst(2, "b", "claude-opus-5-5")]
        self.build(rows)
        self.assertEqual(self.q("SELECT request_model, response_model FROM turns"), [("claude-sonnet-5-5", "claude-opus-5-5")])

    def test_synthetic_model_is_not_a_session_model(self):
        rows = [rec("user", 0, "go"), self.asst(1, "x", "<synthetic>"), self.asst(2, "b", "claude-opus-5-5")]
        self.build(rows)
        self.assertEqual(self.q("SELECT request_model FROM sessions"), [("claude-opus-5-5",)])
        self.assertEqual(self.q("SELECT request_model, response_model FROM turns"), [("claude-opus-5-5", "claude-opus-5-5")])

    def test_records_carry_model_and_legacy_default(self):
        self.ok("note", "tagged", "--model", "claude-sonnet-5-5", root=self.root)
        self.raw_append(dict(type="note", id="n-00000009", text="old"))
        self.build(self.switching())
        got = dict(self.q("SELECT id_, model FROM (SELECT json_extract(fields,'$.id') AS id_, model FROM records WHERE type='note')"))
        self.assertEqual(sorted(got.values()), ["claude-sonnet-5-5", "unknown:legacy"])
        self.assertEqual(self.q("SELECT count(*) FROM records WHERE model IS NULL OR model=''"), [(0,)])

    def test_record_joins_session_by_by_and_turn_by_time(self):
        rows = self.switching()
        self.ok("--by", SID, "note", "from the session", "--model", "claude-opus-5-5", root=self.root)
        self.ok("note", "stranger", root=self.root)
        self.build(rows)
        j = dict((json_id, (s, t)) for json_id, s, t in self.q("SELECT json_extract(fields,'$.text'), session_id, turn_id FROM records WHERE type='note'"))
        self.assertEqual(j["stranger"], (None, None))
        self.assertEqual(j["from the session"][0], SID)

    def test_record_joins_by_awt_session_env(self):
        self.ok("note", "via env", root=self.root, env=dict(self.env, AWT_SESSION=SID))
        self.build(self.switching())
        self.assertEqual(self.q("SELECT session_id FROM records WHERE type='note'"), [(SID,)])

    def test_turn_join_uses_the_time_window(self):
        rows = self.switching()
        self.put(rows)
        self.ok("note", "late", root=self.root, env=dict(self.env, AWT_SESSION=SID))
        self.ok("ingest", "--source", "claude", "--rebuild", root=self.root)
        # the note is stamped now, after the last fixture turn began, but outside the session's window
        t = self.q("SELECT turn_id FROM records WHERE type='note'")[0][0]
        self.assertIsNone(t)

    def test_rebuild_is_still_byte_identical(self):
        self.build(self.switching())
        a = self.dump()
        self.ok("ingest", "--source", "claude", "--rebuild", root=self.root)
        self.assertEqual(a, self.dump())


if __name__ == "__main__":
    unittest.main()
