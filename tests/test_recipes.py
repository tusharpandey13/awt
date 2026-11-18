"""docs/recipes (ARCHITECTURE-v2 section 11): every question has a recipe; every recipe runs on a fixture store and returns the expected rows.
The store is built by awt (so the tables are awt's own) and then filled from fixtures/recipes-v0/data.sql: fictional parsekit/lexgen data."""
import glob, json, os, re, sqlite3, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_ingest import SID, rec
from test_providers import PI, Prov, build_db
from test_store import Store, result, tool_use
from test_usage import FX as CCUSAGE_FX, SID2, asst, sess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECIPES = os.path.join(ROOT, "docs", "recipes")
FX = os.path.join(ROOT, "fixtures", "recipes-v0")
NOW = "2026-11-16T12:00:00Z"
PARAMS = {"now": NOW, "retention_days": ""}
QUESTIONS = 32


def headers(path):
    h = {}
    with open(path, encoding="utf-8") as g:
        for ln in g:
            m = re.match(r"-- (\w+): (.*)$", ln.rstrip("\n"))
            if not m:
                break
            h[m.group(1)] = m.group(2)
    return h


def recipes():
    out = {}
    for p in sorted(glob.glob(os.path.join(RECIPES, "*.sql"))):
        h = headers(p)
        if h.get("kind") == "duckdb":
            continue
        out[os.path.basename(p)[:-4]] = (p, h)
    return out


def run(db, path):
    with open(path, encoding="utf-8") as g:
        sql = g.read()
    cur = db.execute(sql, {k: v for k, v in PARAMS.items() if (":" + k) in sql})
    return [[c[0] for c in cur.description]] + [list(r) for r in cur.fetchall()]


class TestRecipes(Store):
    def setUp(self):
        super().setUp()
        self.put([rec("user", 0, "hi"), rec("assistant", 1, "hello")])
        self.ok("ingest", "--source", "claude", root=self.root)
        db = sqlite3.connect(self.db)
        with open(os.path.join(FX, "data.sql"), encoding="utf-8") as g:
            db.executescript(g.read())
        db.commit()
        db.close()
        self.ro = sqlite3.connect("file:%s?mode=ro" % self.db, uri=True)
        self.addCleanup(self.ro.close)
        with open(os.path.join(FX, "expected.json"), encoding="utf-8") as g:
            self.expected = json.load(g)

    def test_one_recipe_per_question_with_complete_headers(self):
        rs = recipes()
        self.assertEqual(len(rs), QUESTIONS)
        qs = [h.get("question") for _, h in rs.values()]
        self.assertEqual(len(set(qs)), QUESTIONS)
        for name, (_, h) in rs.items():
            for k in ("question", "level", "tables", "status"):
                self.assertTrue(h.get(k), "%s lacks '-- %s:'" % (name, k))
            self.assertIn(h["status"], ("real", "partial", "stub"), name)
            if h["status"] in ("stub", "partial"):
                self.assertTrue(h.get("needs"), "%s is %s without '-- needs:'" % (name, h["status"]))
                with open(rs[name][0], encoding="utf-8") as g:
                    self.assertIn("'needs data'", g.read(), name)
            else:
                self.assertNotIn("needs", h, name)
        self.assertEqual(sorted(self.expected), sorted(rs), "expected.json must hold exactly the recipes")

    def test_every_recipe_returns_the_expected_rows(self):
        for name, (path, h) in recipes().items():
            with self.subTest(recipe=name):
                got = run(self.ro, path)
                self.assertEqual(got, self.expected[name])
                if h["status"] == "stub":
                    self.assertEqual(len(got), 2)
                    self.assertEqual(got[1][0], "needs data")
                else:
                    self.assertGreater(len(got), 1, "a recipe on the fixture must return rows")

    def test_schema_md_documents_every_table_and_view(self):
        with open(os.path.join(ROOT, "docs", "schema.md"), encoding="utf-8") as g:
            doc = g.read()
        names = [r[0] for r in self.ro.execute("select name from sqlite_master where type in ('table', 'view') and name not like 'fts_text_%' order by name")]
        self.assertIn("usage", names)
        for n in names:
            self.assertRegex(doc, r"(?m)^### .*\b%s\b" % re.escape(n), "docs/schema.md has no section for %s" % n)
        self.assertIn("Schema version %s " % dict(self.ro.execute("select key, value from schema_meta"))["schema_version"], doc)
        for name in recipes():
            self.assertIn("`%s`" % name, doc, "docs/schema.md does not mention %s" % name) if headers(recipes()[name][0])["status"] != "real" else None

    def test_recipes_do_not_write(self):
        for name, (path, _) in recipes().items():
            with open(path, encoding="utf-8") as g:
                sql = "\n".join(x for x in g.read().lower().splitlines() if not x.startswith("--"))
            sql = re.sub(r"'[^']*'", "''", sql)
            self.assertNotRegex(sql, r"\b(insert|update|delete|drop|create|alter|attach|pragma)\b", name)

    def test_recipes_run_with_blank_params(self):
        """Datasette sends blank strings for parameters the person leaves empty."""
        for name, (path, _) in recipes().items():
            with self.subTest(recipe=name), open(path, encoding="utf-8") as g:
                sql = g.read()
                self.ro.execute(sql, {k: "" for k in ("now", "retention_days") if (":" + k) in sql}).fetchall()


def run_named(db, name):
    return run(db, os.path.join(RECIPES, name + ".sql"))


class TestRecipesOnIngestedData(Prov):
    """The recipes against a store built by awt's own adapters (Claude with a subagent file and a resumed copy, pi with a branch, opencode, ccusage, hook events, records written by the verbs),
    plus a small hand-written supplement for rows no adapter produces yet (supplement.sql). The numbers asserted here are worked out by hand in the comments."""
    def setUp(self):
        super().setUp()
        self.init()
        find = tool_use(1, "t1", "Bash", {"command": "awt find tokenizer"}, "searching")
        find["message"].update(id="m1", usage={"input_tokens": 100, "output_tokens": 10, "cache_read_input_tokens": 900, "cache_creation_input_tokens": 50})
        read = tool_use(3, "t2", "Read", {"file_path": "docs/plan.md"}, "reading the plan")
        read["message"].update(id="m2", usage={"input_tokens": 120, "output_tokens": 20, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 0})
        hits = "docs/plan.md:3: the tokenizer plan\nREADME.md:1: tokenizer for parsekit\nevent:d-0000abcd: use a regex tokenizer"
        last = asst(7, "tests are green", "m3", 80, 30, cr=1100)
        last["parentUuid"] = "u-4"  # 09:07, three minutes after the prompt at 09:04
        parent = [rec("user", 0, "add a tokenizer to parsekit"), find, result(2, "t1", hits), read, rec("user", 4, "run the tests"), asst(5, "running", "m4", 70, 5, cr=1000), last]
        parent[5]["parentUuid"] = "u-4"
        self.put(parent)
        self.put(sess([rec("user", 0, "sub task"), asst(1, "sub done", "s1", 1000, 0)], SID), path=self.src(sub="agent-x"))
        self.put(parent + sess([rec("user", 8, "go on"), asst(9, "more", "m9", 7, 0)], SID2), path=self.src(SID2))
        self.put_pi()
        build_db(self.ocdb)
        self.put_paseo()
        self.ccusage()
        self.ok("ingest", "--source", "all", root=self.root)
        self.ok("ingest", "--source", "ccusage", root=self.root)
        env = dict(self.env, AWT_SESSION=SID)  # the records name the session they were written in
        self.ok("decide", "use a regex tokenizer for the lexer", "--why", "simple and fast", "--related", "0", env=env)
        self.ok("decide", "switch the lexer to a regex based tokenizer", "--why", "simple", "--related", "0", env=env)
        self.ok("decide", "pin the python version", "--why", "ci", "--related", "0", env=env)
        self.ok("ask", "which regex flavour should the lexer use", "--related", "0", env=env)
        self.ok("ask", "what regex flavour does the lexer need", "--related", "0", env=env)
        for phase, cmd, tid in (("PreToolUse", "git push origin feat/x", "toolu_1"), ("PostToolUse", "git push origin feat/x", "toolu_1"),
                                ("PreToolUse", "git push origin feat/x", "toolu_2"), ("PostToolUse", "git push origin feat/x", "toolu_2"),  # the same push again: a resend, seen after
                                ("PreToolUse", "gh pr merge 4 --squash", "toolu_3"), ("PermissionDenied", "gh pr merge 4 --squash", "toolu_3")):  # a person said no: attempt 2, not a resend
            self.ok("ingest", "--event", "--hook", input=json.dumps({"hook_event_name": phase, "session_id": "s", "cwd": self.tmp, "tool_name": "Bash", "tool_input": {"command": cmd}, "tool_use_id": tid}))
        self.ok("ingest", "--source", "claude", root=self.root)
        db = sqlite3.connect(self.db)
        with open(os.path.join(FX, "supplement.sql"), encoding="utf-8") as g:
            db.executescript(g.read())
        db.commit()
        db.close()
        self.ro = sqlite3.connect("file:%s?mode=ro" % self.db, uri=True)
        self.addCleanup(self.ro.close)

    def ccusage(self):
        d = os.path.join(self.tmp, "bin")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "ccusage")
        with open(os.path.join(CCUSAGE_FX, "session.json")) as g:
            d = json.load(g)
        d["session"][0]["metadata"]["lastActivity"] = "2026-10-03T09:10:00.000Z"  # covers this session's last billed message (09:07)
        with open(os.path.join(d_ := os.path.join(self.tmp, "bin"), "cc.json"), "w") as g:
            json.dump(d, g)
        with open(p, "w") as g:
            g.write("#!/bin/sh\ncat '%s'\n" % os.path.join(d_, "cc.json"))
        os.chmod(p, 0o755)
        self.env["AWT_CCUSAGE"] = p

    def rows(self, name):
        got = run_named(self.ro, name)
        return got[0], got[1:]

    def test_every_recipe_runs_on_ingested_data(self):
        for name in recipes():
            with self.subTest(recipe=name):
                run_named(self.ro, name)

    def one(self, name, **kw):
        head, rows = self.rows(name)
        return [dict(zip(head, r)) for r in rows]

    def test_cost_is_counted_once_across_a_subagent_file_and_a_resumed_copy(self):
        # ccusage covers the parent conversation (its row: input 600 + 400 = 1000, cost 0.03 + 0.0125; the subagent's 1000 and the parent's own messages are inside it) and the resumed
        # session adds its own 7. The pi session is covered by its ccusage row (cost 0.002); opencode has 0.010 + 0.002 of its own: 0.0425 + 0.002 + 0.012 = 0.0565.
        cost, inp = self.ro.execute("select round(sum(cost_usd), 4), sum(usage_input_tokens) from usage_best where provider_name = 'claude_code'").fetchone()
        self.assertEqual((cost, inp), (0.0425, 1007))
        self.assertEqual(self.ro.execute("select round(sum(cost_usd), 4) from usage_best").fetchone(), (0.0565,))
        self.assertEqual(self.one("l1-cost-sessions-agents-per-project-month")[0]["cost_usd"], 0.0565)

    def test_cache_read_share(self):
        # claude-test-1: cache read 2000 of input 600 + 7, cache read 2000, cache write 100 = 2000 / 2707 = 0.739
        self.assertIn({"metric": "model", "key": "claude-test-1", "cache_share": 0.739}, self.one("l8-cache-read-share"))

    def test_latency_percentiles_are_request_latencies(self):
        # six distinct Claude replies: m1, m2, m4, s1 and m9 answered a minute after their request; m3 three minutes after the prompt at 09:04 (a reply copied into another file counts once)
        rows = {(r["metric"], r["model"]): r for r in self.one("l8-latency-percentiles")}
        c = rows[("message_latency_ms", "claude-test-1")]
        self.assertEqual((c["samples"], c["p50"], c["p90"]), (6, 60000.0, 180000.0))

    def test_resends_and_denied_retries_are_different_things(self):
        by = {r["rule"]: r for r in self.one("l7-effects-by-rule")}
        self.assertEqual((by["git push"]["effects"], by["git push"]["resent"], by["git push"]["denied_retries"]), (2, 1, 0))
        self.assertEqual((by["gh pr merge"]["effects"], by["gh pr merge"]["resent"], by["gh pr merge"]["denied_retries"]), (1, 0, 1))

    def test_failed_turn_cost_has_tokens_and_a_prorated_claude_cost(self):
        # turn 1 of the parent session: m4 (70 + 5) and m3 (80 + 30): 150 in, 35 out. ccusage cost 0.03 for claude-test-1 over the conversation's 5485 tokens; this turn has 1075 + 1210 = 2285
        r = self.one("l8-failed-turn-cost")
        self.assertEqual([(x["outcome"], x["turns"], x["input_tokens"], x["output_tokens"], x["ccusage_prorated_usd"]) for x in r], [("failed", 1, 150, 35, round(0.03 * 2285 / 5485, 4))])

    def test_turns_before_the_first_record(self):
        r = {x["session_id"]: x for x in self.one("l6-prompt-to-first-record")}[SID]
        self.assertEqual((r["turns"], r["first_record_turn"], r["turns_before_first_record"], r["seconds_to_first_record"]), (2, 1, 1, 270.0))  # 09:00:00 to 09:04:30

    def test_find_use_follows_a_hit_to_a_later_read(self):
        # the find result names docs/plan.md, README.md and d-0000abcd; the next tool call reads docs/plan.md. The resumed file repeats the call, so two sessions
        self.assertEqual([(r["verb"], r["calls"], r["sessions"], r["calls_with_hits"], r["calls_with_a_used_hit"]) for r in self.one("l7-find-use")], [("find", 2, 2, 2, 2)])

    def test_redecisions_lists_candidate_pairs_in_one_node_within_14_days(self):
        r = self.one("l7-redecisions")
        self.assertEqual(sorted((x["type"], x["days_apart"], x["same_meaning"]) for x in r), [("decision", 7.0, "needs data"), ("question", 10.0, "needs data")])  # "pin the python version" matches nothing

    def test_history_at_risk_matches_subagent_files_and_uses_the_last_record(self):
        ids = [r["session_id"] for r in self.one("l5-history-at-risk")]
        self.assertIn(SID + ".agent-x", ids)

    def test_weeks_are_iso_weeks(self):
        self.assertIn({"week_start": "2026-09-28", "provider_name": "claude_code", "model": "claude-test-1", "sessions": 3}, self.one("l5-sessions-per-provider-model-week"))


if __name__ == "__main__":
    unittest.main()
