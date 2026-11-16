"""docs/recipes (ARCHITECTURE-v2 section 11): every question has a recipe; every recipe runs on a fixture store and returns the expected rows.
The store is built by awt (so the tables are awt's own) and then filled from fixtures/recipes-v0/data.sql: fictional parsekit/lexgen data."""
import glob, json, os, re, sqlite3, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_ingest import rec
from test_store import Store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECIPES = os.path.join(ROOT, "docs", "recipes")
FX = os.path.join(ROOT, "fixtures", "recipes-v0")
NOW = "2026-11-16T12:00:00Z"
PARAMS = {"now": NOW, "retention_days": ""}
QUESTIONS = 31


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


if __name__ == "__main__":
    unittest.main()
