"""SPEC, Unknown verb: a first word that is not a verb prints the right command and exits 2, touching nothing."""
import os, unittest

from test_awt import Base


def snapshot(top):
    return sorted((os.path.join(d, f), os.path.getmtime(os.path.join(d, f))) for d, _, fs in os.walk(top) for f in fs)


class UnknownVerb(Base):
    def test_lookup_words_point_at_find_like(self):
        for w in "crossref xref related similar recall context lookup search grep".split():
            r = self.bad(w, "parser", "rewrite", code=2)
            lines = r.stderr.strip().splitlines()
            self.assertEqual(lines[0], "error: awt: no verb '%s'" % w)
            self.assertIn('awt find --like "parser rewrite"', lines[1])
            self.assertIn("awt find TERM", lines[1])
            self.assertEqual(r.stdout, "")
            self.assertEqual(len(lines), 2)

    def test_no_args_uses_topic_placeholder(self):
        self.assertIn('--like "TOPIC"', self.bad("crossref", code=2).stderr)

    def test_other_intents(self):
        for w in "handoff brief load show".split():
            self.assertTrue(self.bad(w, code=2).stderr.rstrip().endswith("fix: awt resume"), w)
        for w in "checkpoint handoff-save".split():
            self.assertIn("awt state --now", self.bad(w, code=2).stderr)
        self.assertTrue(self.bad("frobnicate", code=2).stderr.rstrip().endswith("fix: awt help"))

    def test_suggestion_is_not_executed_and_nothing_is_written(self):
        self.init()
        before = snapshot(self.tmp)
        self.bad("crossref", "x", code=2)
        self.bad("save", code=2)
        self.assertEqual(snapshot(self.tmp), before)

    def test_real_verbs_and_flags_unaffected(self):
        self.init()
        self.ok("find", "--like", "x")
        self.ok("help")
        self.ok("--version")


if __name__ == "__main__":
    unittest.main()
