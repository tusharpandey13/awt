#!/usr/bin/env python3
"""A scripted ACP agent for plugin tests. Speaks JSON-RPC over stdio.

A prompt of the form `RUN: <shell command>` runs the command in the agent's own environment and
replies with `exit=<code> <output>`. Any other prompt is echoed. This lets a test play the part of
an agent calling `awt`, with exactly the environment Paseo launched it with."""
import json, os, subprocess, sys


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def reply(i, result):
    send({"jsonrpc": "2.0", "id": i, "result": result})


def say(sid, text):
    send({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": sid, "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}}})


def main():
    n = 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        m = json.loads(line)
        i, method, p = m.get("id"), m.get("method"), m.get("params") or {}
        if method == "initialize":
            reply(i, {"protocolVersion": 1, "agentCapabilities": {"loadSession": False, "promptCapabilities": {}}, "authMethods": []})
        elif method == "session/new":
            n += 1
            reply(i, {"sessionId": "fake-%d-%d" % (os.getpid(), n)})
        elif method == "session/prompt":
            text = "".join(b.get("text", "") for b in p.get("prompt", []) if isinstance(b, dict))
            if text.startswith("RUN:"):
                r = subprocess.run(text[4:].strip(), shell=True, capture_output=True, text=True, cwd=os.getcwd())
                say(p["sessionId"], "exit=%d %s%s" % (r.returncode, r.stdout, r.stderr))
            else:
                say(p["sessionId"], "echo: " + text)
            reply(i, {"stopReason": "end_turn"})
        elif i is not None:
            reply(i, {})


if __name__ == "__main__":
    main()
