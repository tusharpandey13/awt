"""relay tests. A fake claude stands in for the model, so these spend no tokens."""
import json, os, shutil, stat, subprocess, sys, tempfile, time, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = r"""#!/bin/sh
# Finds the unit id in the prompt, logs the call, then acts on the unit's behaviour file.
prompt="$2"
id=$(printf '%s\n' "$prompt" | sed -n 's/^Unit: //p' | head -1)
effort=$(printf '%s\n' "$*" | sed -n 's/.*--effort \([a-z]*\).*/\1/p')
echo "$id $effort" >> calls.log
printf '%s\n' "$prompt" > "prompt-$id.txt"
case "$(cat "behave-$id" 2>/dev/null)" in
  hang) sleep 60 ;;
  crash) exit 3 ;;
  silent) ;;
  fix-on-retry) [ "$effort" = high ] && echo ok > fixed.flag; echo "verdict: x" > "docs/$id.out.md" ;;
  *) echo "verdict: ok" > "docs/$id.out.md" ;;
esac
echo '{"type":"result","subtype":"success","is_error":false,"result":"did it","total_cost_usd":0.25}'
"""


class Relay(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="awt-relay-")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        shutil.copy2(os.path.join(REPO, "awt"), self.d)
        shutil.copy2(os.path.join(REPO, "relay"), self.d)
        self.fake = os.path.join(self.d, "fake-claude")
        with open(self.fake, "w") as f:
            f.write(FAKE)
        os.chmod(self.fake, os.stat(self.fake).st_mode | stat.S_IEXEC)
        subprocess.run(["./awt", "init", "--goal", "g", "--done", "d"], cwd=self.d, check=True, capture_output=True)

    def plan(self, units, **top):
        with open(os.path.join(self.d, "plan.json"), "w") as f:
            json.dump(dict(units=units, **top), f)

    def behave(self, uid, what):
        with open(os.path.join(self.d, "behave-" + uid), "w") as f:
            f.write(what)

    def relay(self, *args, timeout=60):
        env = dict(os.environ, RELAY_CLAUDE=self.fake)
        return subprocess.run(["./relay"] + list(args), cwd=self.d, env=env, capture_output=True, text=True, timeout=timeout)

    def calls(self):
        try:
            with open(os.path.join(self.d, "calls.log")) as f:
                return f.read().split("\n")[:-1]
        except FileNotFoundError:
            return []

    def test_order_and_summary(self):
        self.plan([{"id": "b", "task": "t", "needs": ["a"]}, {"id": "a", "task": "t"}])
        r = self.relay("run", "plan.json")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual([c.split()[0] for c in self.calls()], ["a", "b"])
        self.assertIn("2 of 2 units passed, $0.50", r.stdout)

    def test_finished_units_skip_and_edited_units_rerun(self):
        self.plan([{"id": "a", "task": "t"}])
        self.relay("run", "plan.json")
        self.relay("run", "plan.json")
        self.assertEqual(len(self.calls()), 1)
        self.plan([{"id": "a", "task": "changed"}])
        self.relay("run", "plan.json")
        self.assertEqual(len(self.calls()), 2)

    def test_failed_check_retries_once_at_higher_effort_with_the_failure(self):
        self.behave("a", "fix-on-retry")
        self.plan([{"id": "a", "task": "t", "check": "test -f fixed.flag || { echo NOT-FIXED; exit 1; }"}])
        r = self.relay("run", "plan.json")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.calls(), ["a medium", "a high"])
        with open(os.path.join(self.d, "prompt-a.txt")) as f:
            self.assertIn("NOT-FIXED", f.read())

    def test_failure_stops_there_and_blocks_only_dependents(self):
        self.behave("a", "crash")
        self.plan([{"id": "a", "task": "t"}, {"id": "b", "task": "t", "needs": ["a"]}, {"id": "c", "task": "t"}])
        r = self.relay("run", "plan.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("blocked", r.stdout)
        ran = {c.split()[0] for c in self.calls()}
        self.assertEqual(ran, {"a", "c"})
        self.assertEqual(len([c for c in self.calls() if c.startswith("a")]), 2)

    def test_null_retry_effort_means_one_attempt(self):
        self.behave("a", "crash")
        self.plan([{"id": "a", "task": "t", "retry_effort": None}])
        self.relay("run", "plan.json")
        self.assertEqual(len(self.calls()), 1)

    def test_missing_output_fails_without_a_check(self):
        self.behave("a", "silent")
        self.plan([{"id": "a", "task": "t", "retry_effort": None}])
        r = self.relay("run", "plan.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("did not write docs/a.out.md", r.stdout)

    def test_timeout_kills_the_worker(self):
        self.behave("a", "hang")
        self.plan([{"id": "a", "task": "t", "timeout": 1, "retry_effort": None}])
        t = time.time()
        r = self.relay("run", "plan.json", timeout=30)
        self.assertLess(time.time() - t, 20)
        self.assertEqual(r.returncode, 1)
        self.assertIn("timed out", r.stdout)

    def test_parallel_units_all_run_and_notes_stay_valid(self):
        self.plan([{"id": "u%d" % i, "task": "t"} for i in range(8)])
        r = self.relay("run", "plan.json", "--jobs", "8")
        self.assertEqual(r.returncode, 0, r.stdout)
        with open(os.path.join(self.d, ".awt", "events.jsonl")) as f:
            rows = [json.loads(x) for x in f]
        self.assertEqual(len([x for x in rows if x["type"] == "note"]), 8)

    def test_worker_prompt_uses_the_scoped_brief(self):
        subprocess.run(["./awt", "state", "--scope", "other", "--now", "OTHER-NOW", "--next", "n"], cwd=self.d, check=True, capture_output=True)
        subprocess.run(["./awt", "state", "--scope", "a", "--now", "MINE-NOW", "--next", "MINE-NEXT"], cwd=self.d, check=True, capture_output=True)
        subprocess.run(["./awt", "state", "--scope", "other", "--now", "OTHER-NEWER", "--next", "OTHER-NEXT"], cwd=self.d, check=True, capture_output=True)
        self.plan([{"id": "a", "task": "t"}])
        self.relay("run", "plan.json")
        with open(os.path.join(self.d, "prompt-a.txt")) as f:
            p = f.read()
        self.assertIn("MINE-NEXT", p)
        self.assertNotIn("OTHER-NEXT", p)

    def test_bad_plans_are_refused_before_any_work(self):
        for bad in ([{"id": "a", "task": "t", "needs": ["a"]}],
                    [{"id": "a", "task": "t", "needs": ["nope"]}],
                    [{"id": "a", "task": "t"}, {"id": "a", "task": "t"}],
                    [{"id": "A B", "task": "t"}],
                    [{"id": "a"}],
                    [{"id": "a", "task": "t", "modle": "x"}]):
            self.plan(bad)
            self.assertEqual(self.relay("run", "plan.json").returncode, 2, bad)
        self.assertEqual(self.calls(), [])

    def test_dry_run_spends_nothing(self):
        self.plan([{"id": "a", "task": "t"}])
        self.assertEqual(self.relay("run", "plan.json", "--dry-run").returncode, 0)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
