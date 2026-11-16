#!/usr/bin/env python3
"""A scripted ACP agent for plugin tests. Speaks JSON-RPC over stdio.

A prompt of the form `RUN: <shell command>` runs the command in the agent's own environment and
replies with `exit=<code> <output>`. Any other prompt is echoed. This lets a test play the part of
an agent calling `awt`, with exactly the environment Paseo launched it with."""
import html, json, os, re, subprocess, sys


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
        wire = os.environ.get("AWT_FAKE_WIRE")
        if wire:  # H1: log every inbound line, so a test can see exactly what the provider received
            with open(wire, "a") as w:
                w.write(line + "\n")
        m = json.loads(line)
        i, method, p = m.get("id"), m.get("method"), m.get("params") or {}
        if method == "initialize":
            reply(i, {"protocolVersion": 1, "agentCapabilities": {"loadSession": True, "promptCapabilities": {}}, "authMethods": []})
        elif method == "session/new":
            n += 1
            reply(i, {"sessionId": "fake-%d-%d" % (os.getpid(), n)})
        elif method == "session/prompt":
            text = "".join(b.get("text", "") for b in p.get("prompt", []) if isinstance(b, dict))
            if "<paseo-system" in text:  # a prompt sent by another agent arrives wrapped in an envelope; use its body
                body = html.unescape(re.sub(r"<paseo-system[^>]*>|</paseo-system>", "", text))
                text = next((l for l in body.splitlines() if l.startswith(("RUN:", "FAIL:"))), text)
            if text.startswith("FAIL:"):  # H4: run the command, then fail the prompt
                subprocess.run(text[5:].strip(), shell=True, capture_output=True, text=True, cwd=os.getcwd(), timeout=60)
                send({"jsonrpc": "2.0", "id": i, "error": {"code": -32000, "message": "scripted failure"}})
                continue
            if text.startswith("RUN:"):
                try:
                    r = subprocess.run(text[4:].strip(), shell=True, capture_output=True, text=True, cwd=os.getcwd(), timeout=60)
                    say(p["sessionId"], "exit=%d %s%s" % (r.returncode, r.stdout, r.stderr))
                except subprocess.TimeoutExpired:
                    say(p["sessionId"], "exit=124 timed out after 60s")
            else:
                say(p["sessionId"], "echo: " + text)
            reply(i, {"stopReason": "end_turn"})
        elif method in ("session/load", "session/resume"):
            reply(i, {})
        elif i is not None:
            reply(i, {})


if __name__ == "__main__":
    main()
