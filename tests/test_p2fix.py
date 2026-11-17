"""Phase 2 review fixes (H1-H3, M1-M3, M5-M7): store tree, incremental build, temp sweep, freshness order, brief cost and presence, FTS5 fallback."""
import json, os, shutil, signal, sqlite3, subprocess, sys, time, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_awt
import test_tree
from test_ingest import SID, rec
from test_store import Store

SID2 = "3f0c1a2b-0000-4000-8000-00000000bbbb"


def second(i, text):
    r = rec("user", i, text)
    r["sessionId"] = SID2
    return r


class TreeIdentity(Store):  # H1
    def n(self, table):
        return self.q("select count(*) from " + table)[0][0]

    def test_ingest_from_a_bare_directory_keeps_the_records(self):
        self.ok("note", "tokenizer notes", root=self.root)
        self.build()
        self.assertEqual((self.n("records"), self.n("nodes")), (2, 1))
        self.ok("ingest", "--source", "claude", root="", cwd=self.tmp)  # no tree anywhere above here
        self.assertEqual((self.n("records"), self.n("nodes")), (2, 1))
        self.assertEqual(self.n("messages"), 6)

    def test_a_task_outside_the_tree_does_not_switch_it(self):
        self.ok("note", "tokenizer notes", root=self.root)
        self.build()
        other = os.path.join(self.tmp, "other")
        os.mkdir(other)
        self.ok("init", "--goal", "g", "--done", "d", root=other)
        self.ok("ingest", "--source", "claude", root="", cwd=other)  # no --dir: this task's own tree is not the store's
        self.assertEqual(self.n("records"), 2)
        self.assertEqual(self.q("select path from nodes"), [(".",)])

    def test_awt_root_names_the_tree(self):
        self.ok("note", "tokenizer notes", root=self.root)
        self.ok("ingest", "--source", "claude", root="", cwd=self.tmp, env=dict(self.env, AWT_ROOT=self.root))
        self.assertEqual(self.n("records"), 2)

    def test_no_tree_known_builds_no_node_rows(self):
        self.build()
        os.unlink(os.path.join(self.store, "ingest", "tree"))
        self.ok("ingest", "--rebuild", root="", cwd=self.tmp)
        self.assertEqual((self.n("records"), self.n("nodes")), (0, 0))


class Incremental(Store):  # H2, M5
    def mark(self, text="SENT"):
        c = sqlite3.connect(self.db)
        c.execute("update messages set text = text || ?", (" " + text,))
        c.commit()
        c.close()

    def test_a_node_log_change_leaves_canonical_tables_alone(self):
        self.build()
        self.mark()
        n = self.ok("note", "extra-fact", root=self.root).stdout.split()[0]
        self.ok("ingest", "--source", "claude", root=self.root)
        self.assertEqual(self.q("select count(*) from messages where text like '% SENT'"), [(6,)])  # not re-derived
        self.assertEqual(self.q("select count(*) from records where record_id=?", n), [(1,)])
        self.assertEqual(self.q("select count(*) from fts_text join fts_ref r on r.id = fts_text.rowid where fts_text match '\"extra\"' and r.kind='record'"), [(1,)])
        before = self.logical()
        self.ok("ingest", "--rebuild", root=self.root)
        got = self.logical()
        got["messages"] = before["messages"]  # the sentinel edit is the only difference
        self.assertEqual({k: v for k, v in got.items() if not k.startswith("fts:") and k != "canonical"}, {k: v for k, v in before.items() if not k.startswith("fts:") and k != "canonical"})

    def test_a_canonical_change_re_derives_only_that_file(self):
        self.build()
        self.put([second(0, "second session zephyr"), second(1, "more")], self.src(SID2))
        self.ok("ingest", "--source", "claude", root=self.root)
        self.mark()
        self.put(self.rows_() + [rec("user", 6, "one more thing")])
        self.ok("ingest", "--source", "claude", root=self.root)
        self.assertEqual(self.q("select count(*) from messages where session_id=? and text like '% SENT'", SID2), [(2,)])  # untouched
        self.assertEqual(self.q("select count(*) from messages where session_id=? and text like '% SENT'", SID), [(0,)])  # re-derived
        self.assertEqual(self.q("select count(*) from messages where session_id=?", SID), [(7,)])
        c = sqlite3.connect(self.db)
        c.execute("update messages set text = replace(text, ' SENT', '')")
        c.commit()
        c.close()
        inc = self.logical()
        self.ok("ingest", "--rebuild", root=self.root)
        self.assertEqual(self.logical(), inc)

    def test_rebuild_is_byte_stable(self):
        self.build()
        self.ok("ingest", "--rebuild", root=self.root)
        a = self.digest()
        self.ok("ingest", "--rebuild", root=self.root)
        self.assertEqual(self.digest(), a)

    def test_fts_is_contentless_and_the_join_columns_are_indexed(self):
        self.build()
        names = {r[0] for r in self.q("select name from sqlite_master")}
        self.assertNotIn("fts_text_content", names)
        for ix in ("ix_turns_session", "ix_records_node", "ix_sessions_node", "ix_messages_turn", "ix_tool_calls_message", "ix_effects_node"):
            self.assertIn(ix, names)
        plan = " ".join(str(r) for r in self.q("explain query plan select * from records where node_id='x' and type='note'"))
        self.assertIn("ix_records_node", plan)


class Leaks(Store):  # H3, M1
    def start(self, *args, sleep="30"):
        return subprocess.Popen([sys.executable, "-I", test_awt.AWT, "--dir", self.root] + list(args), env=dict(self.env, AWT_TEST_BUILD_SLEEP=sleep),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=self.tmp)

    def wait_for(self, fn, secs=20):
        end = time.time() + secs
        while time.time() < end:
            if fn():
                return True
            time.sleep(0.05)
        return False

    def tmps(self):
        return sorted(f for f in os.listdir(self.store) if f.startswith("store.db") and f.endswith(".tmp")) if os.path.isdir(self.store) else []

    def test_a_killed_build_is_swept_by_the_next_ingest_and_doctor_reports_it(self):
        self.put(self.rows_())
        p = self.start("ingest", "--source", "claude", "--rebuild")
        self.assertTrue(self.wait_for(self.tmps))
        os.kill(p.pid, signal.SIGKILL)
        p.wait()
        self.assertEqual(len(self.tmps()), 1)
        r = self.awt("doctor", root=self.root)
        self.assertRegex(r.stdout, r"warn .*store\.db\.\d+\.tmp")
        self.ok("ingest", "--source", "claude", root=self.root)
        self.assertEqual(self.tmps(), [])
        self.assertEqual(sorted(f for f in os.listdir(self.store) if f.startswith("store.db")), ["store.db"])
        self.assertNotRegex(self.awt("doctor", root=self.root).stdout, r"warn .*\.tmp")

    def test_a_write_during_a_build_is_not_marked_fresh(self):
        self.put(self.rows_())
        p = self.start("ingest", "--source", "claude", sleep="3")
        self.assertTrue(self.wait_for(self.tmps))
        n = self.ok("note", "landed-midbuild", root=self.root).stdout.split()[0]
        p.wait(timeout=60)
        self.ok("ingest", "--source", "claude", root=self.root)
        self.assertEqual(self.q("select count(*) from records where record_id=?", n), [(1,)])


class Briefs(test_tree.TreeBase):  # M2, M3, M7
    def b(self, node):
        return test_awt.slurp(os.path.join(node, "BRIEF.md"))

    def test_a_write_runs_git_only_for_the_written_node(self):  # M2
        root, ws, task, agent, sub = self.chain()
        for i in range(3):
            self.mk("agent", "extra-%d" % i, task)
        repo = os.path.join(self.tmp, "repo")
        os.mkdir(repo)
        subprocess.run(["git", "init", "-q", repo], check=True, env=self.env)
        self.ok("ref", repo, "--title", "repo", "--kind", "repo", root=task)
        self.ok("state", "--now", "n", "--next", "n", root=task)
        shim = os.path.join(self.tmp, "shim")
        os.mkdir(shim)
        log = os.path.join(self.tmp, "git.log")
        with open(os.path.join(shim, "git"), "w") as g:
            g.write('#!/bin/sh\necho "$@" >> %s\nexec %s "$@"\n' % (log, shutil.which("git")))
        os.chmod(os.path.join(shim, "git"), 0o755)
        self.ok("decide", "a-fact-choice", "--why", "w", root=task, env=dict(self.env, PATH=shim + os.pathsep + self.env["PATH"]))
        calls = len(test_awt.slurp(log).splitlines())
        self.assertLessEqual(calls, 2, calls)  # log and status of the one written node; parent and agents get no git section
        self.assertIn("a-fact-choice", self.b(agent))

    def test_reopening_a_keyed_agent_writes_its_brief(self):  # M3
        root, ws, task, agent, sub = self.chain()
        k = self.ok("init", "--kind", "agent", "--name", "keyed", "--key", "paseo:agent/k1", root=task).stdout.split()[1]
        node = os.path.join(task, k)
        os.unlink(os.path.join(node, "BRIEF.md"))
        self.ok("decide", "task-choice", "--why", "w", root=task)  # lineage moved on
        os.unlink(os.path.join(node, "BRIEF.md"))
        self.ok("init", "--kind", "agent", "--name", "keyed", "--key", "paseo:agent/k1", root=task)
        self.assertIn("task-choice", self.b(node))

    def test_a_node_from_before_phase_2_gets_ignore_and_brief_on_write(self):  # M7
        self.ok("init", "--goal", "g", "--done", "d", root=self.top)
        gi = os.path.join(self.top, ".gitignore")
        with open(gi, "w") as g:
            g.write("scratch/\n.awt/claims/\n")
        os.unlink(os.path.join(self.top, "BRIEF.md"))
        subprocess.run(["git", "init", "-q", self.top], check=True, env=self.env)
        self.ok("note", "later", root=self.top)
        self.assertIn("BRIEF.md", test_awt.slurp(gi).splitlines())
        st = subprocess.run(["git", "-C", self.top, "status", "--porcelain"], capture_output=True, text=True, env=self.env).stdout
        self.assertNotIn("BRIEF.md", st)


class NoFts5(test_awt.Base):  # M6
    def test_find_like_falls_back_and_ranks_the_same_words(self):
        self.init()
        self.ok("note", "gateway timeout is thirty seconds")
        self.ok("note", "unrelated lunch order")
        env = dict(self.env, AWT_TEST_NO_FTS5="1")
        want = self.ok("find", "--like", "gateway timeout seconds").stdout
        got = self.awt("find", "--like", "gateway timeout seconds", env=env)
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("gateway timeout is thirty seconds", got.stdout)
        self.assertNotIn("lunch", got.stdout)
        self.assertEqual(got.stdout, want)

    def test_decide_still_shows_related_lines_without_fts5(self):
        self.init()
        self.ok("decide", "use a trie for lookups", "--why", "fast lookups")
        r = self.awt("decide", "use a trie for lookup speed", "--why", "fast", env=dict(self.env, AWT_TEST_NO_FTS5="1"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("related", r.stdout)


if __name__ == "__main__":
    unittest.main()
