"""Active recall (SPEC.md, "Active recall"). End to end: every check runs the real awt in a temp HOME."""
import datetime, json, os, re, time, unittest

import test_awt
import test_tree

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RecallBase(test_tree.TreeBase):
    def world(self):
        """root > parsekit > retry-bug > chat-1, and root > billing > main."""
        root = self.make_root()
        pk = self.mk("workspace", "parsekit", root)
        retry = self.mk("task", "retry-bug", pk, "--goal", "fix retries", "--done", "merged")
        agent = self.mk("agent", "chat-1", retry)
        bill = self.mk("workspace", "billing", root)
        main = self.mk("task", "main", bill, "--goal", "billing", "--done", "ongoing")
        return root, pk, retry, agent, main

    def like(self, text, *extra, root, **kw):
        return self.ok("find", "--like", text, *extra, root=root, cwd=kw.pop("cwd", self.top), **kw).stdout.splitlines()

    def related(self, out):
        return [l for l in out.splitlines() if l.startswith("related:")]


class Like(RecallBase):
    def test_rare_word_outranks_common_word(self):  # T-R1a
        root, pk, retry, agent, main = self.world()
        for i in range(6):
            self.ok("note", "cache layer %d is warm" % i, root=retry)
        self.ok("note", "jitter spreads the clients", root=main)
        lines = self.like("cache jitter", root=agent)
        self.assertGreaterEqual(len(lines), 2, lines)
        self.assertIn("jitter", lines[0])
        self.assertIn("cache", lines[1])

    def test_superseded_and_auto_never_match(self):  # T-R1b
        root, pk, retry, agent, main = self.world()
        old = self.ok("decide", "use fixed backoff always", "--why", "simple wins", "--related", "0", root=retry).stdout.split()[0]
        self.ok("decide", "use exponential backoff always", "--why", "simple wins", "--supersedes", old, "--related", "0", root=retry)
        self.ok("state", "--scope", "auto", "--now", "[auto] backoff discussed at length", "--next", "none", root=main)
        self.ok("state", "--now", "backoff measured at length", "--next", "ship", root=main)
        out = "\n".join(self.like("backoff simple length", root=root))
        self.assertNotIn(old, out)
        self.assertNotIn("fixed backoff", out)
        self.assertIn("exponential backoff", out)
        self.assertNotIn("[auto]", out)
        self.assertIn("backoff measured", out)

    def test_node_prefix_from_agent_node_and_outside_the_tree(self):  # T-R1c
        root, pk, retry, agent, main = self.world()
        nid = self.ok("note", "gateway timeout is thirty seconds", root=main).stdout.split()[0]
        inside = self.awt("find", "--like", "gateway timeout seconds", root=agent, cwd=agent)
        self.assertEqual(inside.returncode, 0, inside.stderr)
        self.assertIn("%s @%s:" % (nid, os.path.relpath(main, agent)), inside.stdout)
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.mkdir(elsewhere)
        outside = self.awt("find", "--like", "gateway timeout seconds", root=agent, cwd=elsewhere)
        self.assertIn("%s @workspaces/billing/tasks/main:" % nid, outside.stdout)  # relative to the tree top, not absolute
        self.assertNotIn(self.tmp, outside.stdout)
        top = self.awt("find", "--like", "gateway timeout seconds", root=agent, cwd=root)
        self.assertIn("%s @workspaces/billing/tasks/main:" % nid, top.stdout)

    def test_rule_decisions_are_boosted(self):  # T-R1d
        root, pk, retry, agent, main = self.world()
        rule = self.ok("decide", "pin the parser version", "--why", "reproducible builds", "--tag", "rule", "--related", "0", root=pk).stdout.split()[0]
        time.sleep(0.01)
        plain = self.ok("decide", "pin the parser version", "--why", "reproducible builds", "--related", "0", root=main).stdout.split()[0]
        lines = self.like("pin parser version reproducible", root=root)
        self.assertTrue(lines[0].startswith(rule), lines)
        self.assertIn("[rule]", lines[0])
        self.assertTrue(lines[1].startswith(plain), lines)

    def test_ties_go_to_the_newest(self):  # T-R1a
        root, pk, retry, agent, main = self.world()
        a = self.ok("note", "tokenizer handles unicode", root=pk).stdout.split()[0]
        time.sleep(0.01)
        b = self.ok("note", "tokenizer handles unicode", root=main).stdout.split()[0]
        lines = self.like("tokenizer unicode", root=root)
        self.assertTrue(lines[0].startswith(b) and lines[1].startswith(a), lines)

    def test_no_hits(self):  # T-R1e
        root, pk, retry, agent, main = self.world()
        self.ok("note", "tokenizer handles unicode", root=pk)
        r = self.ok("find", "--like", "zebra quagga", root=agent)
        self.assertEqual(r.stdout, "no related records\n")

    def test_like_with_term_is_a_usage_error(self):  # T-R1f
        root, pk, retry, agent, main = self.world()
        self.bad("find", "--like", "some text", "term", root=agent, code=2)

    def test_limit_and_line_cut(self):  # T-R1h
        root, pk, retry, agent, main = self.world()
        for i in range(12):
            self.ok("note", "tokenizer unicode case %d %s" % (i, "x" * 250), root=pk)
        self.assertEqual(len(self.like("tokenizer unicode", root=root)), 10)
        out = self.like("tokenizer unicode", "--limit", "3", root=root)
        self.assertEqual(len(out), 3)
        self.assertTrue(all(len(l) <= 200 for l in out), [len(l) for l in out])
        self.assertEqual(len(self.like("tokenizer unicode", "--limit", "40", root=root)), 12)
        for bad in ("0", "41", "x"):
            self.bad("find", "--like", "tokenizer unicode", "--limit", bad, root=root, code=2)

    def test_scope_flags_narrow_and_answers_and_refs_and_ids(self):  # T-R1i
        root, pk, retry, agent, main = self.world()
        q = self.ok("ask", "Is the gateway timeout a hard limit?", "--related", "0", root=main).stdout.split()[0]
        self.ok("answer", q, "Yes, the gateway sets it", root=main)
        self.ok("ref", "https://example.com/gateway", "--title", "Gateway timeout reference", "--why", "limits", root=pk)
        out = "\n".join(self.like("gateway timeout", root=root))
        self.assertIn("%s @workspaces/billing/tasks/main: Is the gateway timeout a hard limit? → Yes, the gateway sets it" % q, out)
        self.assertIn("Gateway timeout reference", out)
        # a decision id is a word of its own
        d = self.ok("decide", "cap retries at five", "--why", "bounded cost", "--related", "0", root=pk).stdout.split()[0]
        self.assertIn(d, self.like("what about " + d, root=root)[0])
        # --down from the workspace reaches only its own tasks; --up from an agent reaches only its ancestors
        self.assertNotIn(q, "\n".join(self.like("gateway timeout", "--down", root=pk)))
        self.assertIn("Gateway timeout reference", "\n".join(self.like("gateway timeout", "--down", root=pk)))
        up = "\n".join(self.like("gateway timeout", "--up", root=agent))
        self.assertIn("Gateway timeout reference", up)
        self.assertNotIn(q, up)


    def test_trailing_punctuation_is_not_part_of_a_word(self):  # T-R1j
        root, pk, retry, agent, main = self.world()
        self.ok("note", "the gateway enforces a hard limit", root=main)
        self.assertEqual(len(self.like("gateway.", root=root)), 1)
        self.assertEqual(len(self.like("limit_ gateway/", root=root)), 1)


    def test_current_node_has_no_prefix_even_from_outside_the_tree(self):  # T-R1c
        root, pk, retry, agent, main = self.world()
        mine = self.ok("note", "gateway timeout is thirty seconds", root=agent).stdout.split()[0]
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.mkdir(elsewhere)
        for args in (("find", "--like", "gateway timeout seconds"),):
            out = self.awt(*args, root=agent, cwd=elsewhere).stdout
            self.assertIn("%s: gateway" % mine, out)
            self.assertNotIn("@", out)
        far = self.ok("decide", "retry gateway timeout", "--why", "gateway timeout seconds matter", root=agent, cwd=elsewhere)
        self.assertIn("related: %s: gateway" % mine, far.stdout)
        self.assertNotIn(self.tmp, far.stdout)

    def test_find_term_tree_keeps_its_absolute_prefix_outside_the_tree(self):  # T-R1c
        root, pk, retry, agent, main = self.world()
        self.ok("note", "zebracorn marker", root=main)
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.mkdir(elsewhere)
        out = self.awt("find", "--tree", "zebracorn", root=agent, cwd=elsewhere).stdout
        self.assertIn("@" + main, out)


class RelatedOnWrite(RecallBase):
    def seed(self, main, n=5):
        for i in range(n):
            self.ok("note", "retry jitter note %d" % i, root=main)

    def test_default_three_and_never_the_new_row(self):  # T-R2a
        root, pk, retry, agent, main = self.world()
        self.seed(main)
        r = self.ok("decide", "retry with jitter", "--why", "retry jitter spreads load", root=agent)
        lines = r.stdout.splitlines()
        self.assertRegex(lines[0], r"^d-[0-9a-f]{8} decided$")
        rel = self.related(r.stdout)
        self.assertEqual(len(rel), 3, r.stdout)
        self.assertEqual(lines[1:], rel)
        self.assertNotIn(lines[0].split()[0], "\n".join(rel))
        self.assertTrue(all(re.match(r"^related: n-[0-9a-f]{8} @", l) for l in rel), rel)

    def test_related_zero_and_env_zero(self):  # T-R2b
        root, pk, retry, agent, main = self.world()
        self.seed(main)
        a = self.ok("decide", "retry with jitter", "--why", "retry jitter", "--related", "0", root=agent)
        self.assertRegex(a.stdout, r"^d-[0-9a-f]{8} decided\n$")
        env = dict(self.env, AWT_RELATED="0")
        b = self.ok("ask", "retry jitter question", root=agent, env=env)
        self.assertRegex(b.stdout, r"^q-[0-9a-f]{8} asked\n$")
        self.assertEqual(b.stderr, "")
        c = self.ok("ask", "retry jitter other", "--related", "2", root=agent, env=env)
        self.assertEqual(len(self.related(c.stdout)), 2)  # the flag beats the environment

    def test_invalid_related(self):  # T-R2c
        root, pk, retry, agent, main = self.world()
        self.seed(main)
        before = self.events_of(agent)
        for bad in ("25", "-1", "x"):
            self.bad("decide", "retry jitter", "--why", "w", "--related", bad, root=agent, code=2)
            self.bad("ask", "retry jitter", "--related", bad, root=agent, code=2)
        self.assertEqual(before, self.events_of(agent))
        r = self.ok("note", "unchanged", root=agent)
        e = self.ok("decide", "retry with jitter", "--why", "retry jitter", root=agent, env=dict(self.env, AWT_RELATED="abc"))
        self.assertIn("AWT_RELATED", e.stderr)
        self.assertEqual(len(self.related(e.stdout)), 3)
        e = self.ok("ask", "retry jitter", root=agent, env=dict(self.env, AWT_RELATED="21"))
        self.assertIn("AWT_RELATED", e.stderr)
        self.assertEqual(len(self.related(e.stdout)), 3)

    def test_ask_shows_an_answer_from_elsewhere(self):  # T-R2d
        root, pk, retry, agent, main = self.world()
        q = self.ok("ask", "Is the gateway timeout a hard limit?", root=main).stdout.split()[0]
        self.ok("answer", q, "Yes, set by the gateway", root=main)
        r = self.ok("ask", "Is the gateway timeout a hard limit for us?", root=agent)
        rel = self.related(r.stdout)
        self.assertEqual(len(rel), 1, r.stdout)
        self.assertIn("%s @" % q, rel[0])
        self.assertTrue(rel[0].endswith("→ Yes, set by the gateway"), rel[0])

    def test_corrupt_events_elsewhere_do_not_fail_the_write(self):  # T-R2e
        root, pk, retry, agent, main = self.world()
        self.seed(main)
        ev = os.path.join(main, ".awt", "events.jsonl")
        with open(ev, "ab") as g:
            g.write(b"\xff\xfe{not json\n" + b'{"v":1,"type":"note"' + b"\0" * 40)
        junk = self.mk("agent", "junk", retry)
        os.remove(os.path.join(junk, ".awt", "events.jsonl"))
        os.mkdir(os.path.join(junk, ".awt", "events.jsonl"))
        r = self.awt("decide", "retry with jitter", "--why", "retry jitter", root=agent)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout.splitlines()[0], r"^d-[0-9a-f]{8} decided$")
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(len(self.rows_of(agent, "decision")), 1)

    def test_a_fault_inside_the_recall_path_keeps_the_write(self):  # T-R2e
        root, pk, retry, agent, main = self.world()
        self.seed(main)
        fault = dict(self.env, AWT_TEST_RECALL_FAULT="1")
        ctl = self.ok("note", "control", root=agent)  # the hook is inert elsewhere
        # the same lookup raises under the hook (find --like has no guard), so the guard in decide/ask is what is tested
        self.assertNotEqual(self.awt("find", "--like", "retry jitter", root=agent, env=fault).returncode, 0)
        for cmd, args in (("decide", ("retry with jitter", "--why", "retry jitter")), ("ask", ("retry jitter question",))):
            r = self.awt(cmd, *args, root=agent, env=fault)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(len(r.stdout.splitlines()), 1, r.stdout)  # the id line only
            self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(len(self.rows_of(agent, "decision")), 1)
        self.assertEqual(len(self.rows_of(agent, "question")), 1)

    def test_empty_related_is_unset_and_a_bad_budget_means_two_seconds(self):  # T-R2c
        root, pk, retry, agent, main = self.world()
        self.seed(main)
        e = self.ok("decide", "retry with jitter", "--why", "retry jitter", root=agent, env=dict(self.env, AWT_RELATED=""))
        self.assertEqual(e.stderr, "")
        self.assertEqual(len(self.related(e.stdout)), 3)
        for bad in ("abc", "-5", "nan", "inf", ""):
            r = self.ok("ask", "retry jitter question", root=agent, env=dict(self.env, AWT_RELATED_MS=bad))
            self.assertEqual(len(self.related(r.stdout)), 3, (bad, r.stdout))
            self.assertNotIn("lookup stopped", r.stdout)

    def test_budget_exceeded_keeps_the_write(self):  # T-R2f
        root, pk, retry, agent, main = self.world()
        self.seed(main)
        r = self.ok("decide", "retry with jitter", "--why", "retry jitter", root=agent, env=dict(self.env, AWT_RELATED_MS="0"))
        lines = r.stdout.splitlines()
        self.assertRegex(lines[0], r"^d-[0-9a-f]{8} decided$")
        self.assertEqual(lines[-1], "related: (lookup stopped at 2 s; run awt find --like ...)")
        self.assertEqual(len(self.rows_of(agent, "decision")), 1)


    def test_related_line_cut_counts_the_prefix(self):  # T-R2g
        root, pk, retry, agent, main = self.world()
        self.ok("note", "backoff jitter " + "x" * 250, root=main)
        r = self.ok("note", "other", root=agent)
        out = self.ok("decide", "backoff jitter", "--why", "spread", root=agent).stdout
        rel = self.related(out)
        self.assertEqual(len(rel), 1)
        self.assertLessEqual(len(rel[0]), 200)


class Pointers(RecallBase):
    def test_template_has_the_like_line(self):  # T-R3a
        self.init()
        self.assertIn('find --like "a sentence"', test_awt.slurp(self.p("AGENTS.md")))
        root = self.make_root()
        self.assertIn('awt find --like "a sentence"', test_awt.slurp(os.path.join(root, "AGENTS.md")))

    def test_plugin_block_is_short_and_points_at_like(self):  # T-R3b
        src = test_awt.slurp(os.path.join(REPO, "paseo-plugin", "server", "prompt.ts"))
        block = re.search(r"AWT_BLOCK = `(.*?)`;", src, re.S).group(1).replace("\\`", "`")
        self.assertLessEqual(len(block), 700, len(block))
        self.assertIn("find --like", block)
        self.assertIn("awt_resume", block)

    def test_session_start_hook_covers_compaction(self):  # T-R5a
        self.init()
        cfg = json.loads(test_awt.slurp(self.p(".claude", "settings.json")))
        entries = cfg["hooks"]["SessionStart"]
        self.assertTrue(entries)
        for e in entries:
            self.assertNotIn("matcher", e)  # no matcher: runs on startup, resume, clear and compact
            self.assertTrue(any("resume --hook" in h["command"] for h in e["hooks"]))


class Since(RecallBase):
    KEYS = {"type", "ts", "by", "id", "scope"}

    def since(self, ts, *extra, root):
        return json.loads(self.ok("list", "--since", ts, *extra, "--json", root=root).stdout)

    def test_rows_at_or_after_the_timestamp(self):  # T-R4a
        root, pk, retry, agent, main = self.world()
        self.ok("note", "before", root=retry)
        time.sleep(0.02)
        cut = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        time.sleep(0.02)
        n = self.ok("note", "after", root=retry).stdout.split()[0]
        d = self.ok("decide", "after too", "--why", "w", "--related", "0", root=retry).stdout.split()[0]
        self.ok("state", "--scope", "auto", "--now", "[auto] x", "--next", "y", root=retry)
        sub = self.ok("note", "from the agent below", root=agent).stdout.split()[0]
        own = self.since(cut, root=retry)
        self.assertEqual([(r["type"], r["id"], r["scope"]) for r in own], [("note", n, None), ("decision", d, None), ("state", None, "auto")])
        for r in own:
            self.assertEqual(set(r), self.KEYS)
        down = self.since(cut, "--down", root=retry)
        self.assertEqual(set().union(*[set(r) for r in down]), self.KEYS | {"node"})
        self.assertTrue(all(set(r) == self.KEYS | {"node"} for r in down))
        self.assertEqual([r["id"] for r in down if r["type"] == "note"], [n, sub])
        self.assertEqual({r["node"] for r in down}, {None, os.path.relpath(agent, retry)})
        # the boundary itself is included, and later rows only
        last = self.rows_of(retry)[-1]["ts"]
        self.assertEqual(len(self.since(last, root=retry)), 1)
        self.assertEqual(self.since("2999-01-01T00:00:00Z", root=retry), [])
        self.assertGreater(len(self.since("2000-01-01T00:00:00Z", root=retry)), 4)  # every type, node and task rows too

    def test_offsets_and_z_in_any_case_mean_the_same_instant(self):  # T-R4a
        root, pk, retry, agent, main = self.world()
        self.ok("note", "one", root=retry)
        want = self.since("2000-01-01T00:00:00Z", root=retry)
        for ts in ("2000-01-01T00:00:00z", "2000-01-01T05:30:00+05:30", "2000-01-01T05:30:00+0530", "1999-12-31T19:00:00-05:00",
                   "1999-12-31T19:00:00-0500", "2000-01-01T00:00:00.5Z", "2000-01-01T00:00:00+00:00"):
            self.assertEqual(self.since(ts, root=retry), want, ts)
        self.assertEqual(self.since("2999-01-01T05:30:00+05:30", root=retry), [])
        # the offset is applied: both of these are instants an hour ahead of now, after the note
        late = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
        self.assertEqual(self.since(late.strftime("%Y-%m-%dT%H:%M:%S+00:00"), root=retry), [])
        self.assertEqual(self.since((late + datetime.timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S+05:00"), root=retry), [])

    def test_naive_bare_and_empty_times_are_usage_errors_with_a_fix(self):  # T-R4a
        root, pk, retry, agent, main = self.world()
        for bad in ("2000-01-01T00:00:00", "2000-01-01", "2000-01-01 00:00:00", "", "  ", "2000-01-01T00:00:00+5", "2000-01-01T00:00:00+25:99"):
            r = self.bad("list", "--since", bad, "--json", root=retry, code=2)
            self.assertIn("fix:", r.stderr, repr(bad))
        self.assertIn("empty", self.bad("list", "--since", "", "--json", root=retry, code=2).stderr)

    def test_usage_errors(self):  # T-R4a
        root, pk, retry, agent, main = self.world()
        self.bad("list", "--since", "yesterday", "--json", root=retry, code=2)
        self.bad("list", "--since", "2026-01-01T00:00:00Z", root=retry, code=2)
        self.bad("list", "--down", "--json", "notes", root=retry, code=2)


if __name__ == "__main__":
    unittest.main()
