"""Local e2e for the compaction context hooks: real opencode and real pi against a fake OpenAI-compatible endpoint (no paid model).
Gated: AWT_E2E_LOCAL=1 (spawns servers; opencode downloads its provider package on first use, so it needs network). TEST-SPEC.md, Compaction context, L1-L2."""
import json, os, shutil, socket, subprocess, sys, tempfile, time, unittest, urllib.parse, urllib.request

import test_awt

ON = os.environ.get("AWT_E2E_LOCAL") == "1"
FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake", "openai-compat.mjs")
TOKEN = "ZQ7777"
FRAME = "awt record for this task"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Local(test_awt.Base):
    def setUp(self):
        super().setUp()
        self.node_dir = os.path.join(self.tmp, "node")
        os.mkdir(self.node_dir)
        self.ok("init", "--goal", "e2e goal", "--done", "done", root=self.node_dir)
        self.ok("decide", "%s is the build codeword" % TOKEN, "--why", "fixture", "--by", "person", root=self.node_dir)
        self.port = free_port()
        self.log = os.path.join(self.tmp, "req.log")
        open(self.log, "w").close()
        self.fake = subprocess.Popen(["node", FAKE, self.log, str(self.port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.fake.kill)
        time.sleep(0.5)
        self.work = os.path.join(self.tmp, "work")
        os.mkdir(self.work)

    def requests(self):
        with open(self.log) as g:
            return [json.loads(json.loads(x)["body"]) for x in g if x.strip()]

    def child_env(self, **kw):
        e = dict(self.env, AWT_DIR=self.node_dir, **kw)
        return e


@unittest.skipUnless(ON and shutil.which("opencode") and shutil.which("node"), "AWT_E2E_LOCAL=1 with opencode and node")
class OpenCode(Local):
    def test_l1_compaction_request_carries_the_brief_and_adds_no_message(self):
        cfg = os.path.join(self.tmp, "oc")
        os.makedirs(os.path.join(cfg, "plugins"))
        with open(os.path.join(cfg, "opencode.json"), "w") as g:
            json.dump({"provider": {"fake": {"npm": "@ai-sdk/openai-compatible", "name": "fake", "options": {"baseURL": "http://127.0.0.1:%d/v1" % self.port, "apiKey": "x"},
                                             "models": {"m": {"name": "m", "limit": {"context": 100000, "output": 4000}}}}}, "model": "fake/m", "autoupdate": False}, g)
        # opencode needs the real HOME for its package cache (a fresh HOME stalls it); every directory it writes or reads config from is a temp one
        env = self.child_env(HOME=os.environ["HOME"], XDG_CONFIG_HOME=os.path.join(self.tmp, "xc"), OPENCODE_CONFIG_DIR=cfg, XDG_DATA_HOME=os.path.join(self.tmp, "d"), XDG_STATE_HOME=os.path.join(self.tmp, "s"), XDG_CACHE_HOME=os.path.join(self.tmp, "c"), OPENCODE_DISABLE_MODELS_FETCH="1", PWD=self.work)  # opencode takes its project directory from $PWD, not the real cwd
        models = os.path.join(os.environ["HOME"], ".cache", "opencode", "models.json")  # without a local copy opencode fetches it at start and can stall offline
        if os.path.exists(models):
            os.makedirs(os.path.join(self.tmp, "c", "opencode"))
            shutil.copy(models, os.path.join(self.tmp, "c", "opencode", "models.json"))
        self.ok("init", "--hooks", "opencode", root="", env=env)
        r = subprocess.run(["opencode", "run", "-m", "fake/m", "say hi"], cwd=self.work, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK summary", r.stdout, r.stdout + r.stderr)
        srv_port = free_port()
        srv = subprocess.Popen(["opencode", "serve", "--port", str(srv_port)], cwd=self.work, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(srv.kill)
        base = "http://127.0.0.1:%d" % srv_port
        for _ in range(40):
            try:
                sid = json.load(urllib.request.urlopen(base + "/session?directory=" + urllib.parse.quote(self.work)))[0]["id"]
                break
            except Exception as e:
                last = repr(e)
                time.sleep(0.5)
        else:
            self.fail("opencode serve did not start: %s" % locals().get("last"))
        n0 = len(self.requests())
        urllib.request.urlopen(urllib.request.Request(base + "/session/%s/summarize" % sid, json.dumps({"providerID": "fake", "modelID": "m"}).encode(), {"content-type": "application/json"}), timeout=60).read()
        reqs = self.requests()[n0:]
        self.assertEqual(len(reqs), 1, "one request: the summary")
        body = json.dumps(reqs[0])
        self.assertIn(FRAME, body)
        self.assertIn(TOKEN, body)
        msgs = json.load(urllib.request.urlopen(base + "/session/%s/message" % sid))
        chat = json.dumps(msgs)
        self.assertNotIn(FRAME, chat, "the brief is in the summarizer prompt, not in a chat message")
        self.assertEqual([m["info"]["role"] for m in msgs], ["user", "assistant", "user", "assistant"], "the compaction adds its own pair and nothing else")


@unittest.skipUnless(ON and shutil.which("pi") and shutil.which("node"), "AWT_E2E_LOCAL=1 with pi and node")
class Pi(Local):
    def test_l2_system_prompt_after_compaction_carries_the_brief_and_adds_no_message(self):
        cfg = os.path.join(self.tmp, "pi")
        os.makedirs(cfg)
        with open(os.path.join(cfg, "models.json"), "w") as g:
            json.dump({"providers": {"fake": {"baseUrl": "http://127.0.0.1:%d/v1" % self.port, "api": "openai-completions", "apiKey": "x",
                                              "models": [{"id": "m", "name": "m", "contextWindow": 100000, "maxTokens": 2000}]}}}, g)
        env = self.child_env(PI_CODING_AGENT_DIR=cfg)
        self.ok("init", "--hooks", "pi", root="", env=env)
        p = subprocess.Popen(["pi", "--mode", "rpc", "--model", "fake/m"], cwd=self.work, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.addCleanup(p.kill)

        def call(msg):
            p.stdin.write(json.dumps(msg) + "\n")
            p.stdin.flush()
            return msg

        def wait_for(pred, secs=60):
            end = time.time() + secs
            while time.time() < end:
                line = p.stdout.readline()
                if not line:
                    break
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if pred(ev):
                    return ev
            self.fail("pi did not answer in time")

        for i in range(3):  # three big turns so a manual compaction has something to summarize
            call({"id": str(i), "type": "prompt", "message": "filler %d: %s" % (i, " ".join("w%d_%d" % (i, k) for k in range(12000)))})
            wait_for(lambda e: e.get("type") == "agent_end")
        n0 = len(self.requests())
        call({"id": "c", "type": "compact"})
        r = wait_for(lambda e: e.get("id") == "c")
        self.assertTrue(r.get("success"), r)
        self.assertEqual(len(self.requests()), n0 + 1, "compaction made one request, the summary")
        call({"id": "n", "type": "prompt", "message": "next turn"})
        wait_for(lambda e: e.get("type") == "agent_end")
        last = self.requests()[-1]
        sysm = json.dumps([m for m in last["messages"] if m["role"] in ("system", "developer")])
        self.assertIn(FRAME, sysm)
        self.assertIn(TOKEN, sysm)
        users = [m for m in last["messages"] if m["role"] == "user"]
        self.assertNotIn(FRAME, json.dumps(users), "nothing was added as a message")


if __name__ == "__main__":
    unittest.main()
