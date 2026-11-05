#!/usr/bin/env python3
"""Agentic chaos harness for awt: cold-start `claude -p` sessions judged by scripts, never a model."""
import argparse
import concurrent.futures as cf
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AWT = os.path.abspath(os.path.join(HERE, "..", "..", "awt"))
sys.path.insert(0, HERE)
import scenarios  # noqa: E402

MODEL, MAX_TURNS, TIMEOUT = "claude-haiku-5-5", "25", 300
SETTINGS = {
    "sandbox": {"enabled": True, "allowUnsandboxedCommands": False, "network": {"allowedDomains": []}},
    "permissions": {"deny": ["Bash(git push *)", "Bash(curl *)", "Bash(rm -rf *)"]},
}


def run_session(prompt, d, settings):
    cmd = ["claude", "-p", prompt, "--model", MODEL, "--output-format", "json", "--max-turns", MAX_TURNS,
           "--allowedTools", "Bash,Read,Write,Edit,Glob,Grep", "--settings", settings]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    s = {"prompt": prompt, "result": "", "cost": 0.0, "infra": None}
    t0 = time.time()
    p = subprocess.Popen(cmd, cwd=d, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        out, err = p.communicate(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        s["infra"] = "timeout after %ds" % TIMEOUT
        out, err = "", ""
    except Exception as e:  # noqa: BLE001
        s["infra"] = "harness error: %r" % e
        out, err = "", ""
    finally:
        try:
            os.killpg(p.pid, signal.SIGKILL)  # no process left behind
        except OSError:
            pass
        try:
            p.communicate(timeout=10)
        except Exception:  # noqa: BLE001
            pass
    s["secs"] = round(time.time() - t0, 1)
    if s["infra"]:
        return s
    try:
        j = json.loads(out)
        if isinstance(j, list):
            j = [x for x in j if isinstance(x, dict) and x.get("type") == "result"][-1]
        s["result"] = j.get("result") or ""
        s["cost"] = float(j.get("total_cost_usd") or 0)
        s["turns"] = j.get("num_turns")
        if j.get("is_error") and j.get("subtype") != "error_max_turns":
            s["infra"] = "claude error: %s %s" % (j.get("subtype"), s["result"][:200])
    except Exception:  # noqa: BLE001
        s["infra"] = "unparseable output rc=%s stderr=%s" % (p.returncode, (err or out)[:300])
    return s


def run_scenario(sc, root, settings, keep):
    d = os.path.join(root, sc["name"])
    os.makedirs(d)
    rep = {"name": sc["name"], "dir": d, "sessions": [], "failures": [], "status": "PASS"}
    try:
        shutil.copy2(AWT, os.path.join(d, "awt"))
        os.chmod(os.path.join(d, "awt"), 0o755)
        rc, out = scenarios.awt(d, "init", "--goal", sc["goal"], "--done", sc["done"])
        if rc != 0:
            raise RuntimeError("awt init failed: " + out[:300])
        ctx = sc["setup"](d) or {}
    except Exception as e:  # noqa: BLE001
        rep.update(status="INFRA", failures=["setup: %r" % e])
        return rep
    results = []
    for stage in sc["stages"]:
        with cf.ThreadPoolExecutor(len(stage)) as ex:
            res = list(ex.map(lambda p: run_session(p, d, settings), stage))
        results.append(res)
        rep["sessions"].extend(res)
    bad = [s["infra"] for s in rep["sessions"] if s["infra"]]
    if bad:
        rep.update(status="INFRA", failures=bad)
        return rep
    try:
        rep["failures"] = sc["check"](d, results, ctx)
    except Exception as e:  # noqa: BLE001
        rep["failures"] = ["TOOL: checker crashed: %r" % e]
    if any(not x.startswith("NOTE") for x in rep["failures"]):
        rep["status"] = "FAIL"
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", action="append", help="scenario name (repeatable)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep temp task dirs")
    ap.add_argument("--report", default=os.path.join(HERE, "last-report.json"))
    a = ap.parse_args()
    chosen = [s for s in scenarios.SCENARIOS if not a.only or s["name"] in a.only]
    if not chosen:
        print("no scenario matches --only"); return 2
    if a.dry_run:
        for s in chosen:
            n = sum(len(st) for st in s["stages"])
            print("%-10s stages=%d sessions=%d  %s" % (s["name"], len(s["stages"]), n, s["stages"][0][0][:60].replace("\n", " ")))
        print("dry-run: %d scenario(s), awt %s" % (len(chosen), "present" if os.path.exists(AWT) else "absent"))
        return 0
    if not os.path.exists(AWT):
        print("awt not found at " + AWT); return 2
    root = tempfile.mkdtemp(prefix="awt-agentic-")
    settings = os.path.join(root, "agent-settings.json")
    with open(settings, "w") as f:
        json.dump(SETTINGS, f)
    with cf.ThreadPoolExecutor(a.workers) as ex:
        reps = list(ex.map(lambda s: run_scenario(s, root, settings, a.keep), chosen))
    for r in reps:
        print("%-5s %-10s %s" % (r["status"], r["name"], "; ".join(r["failures"])))
    cost = sum(s["cost"] for r in reps for s in r["sessions"])
    c = {k: sum(r["status"] == k for r in reps) for k in ("PASS", "FAIL", "INFRA")}
    print("\n%(PASS)d pass, %(FAIL)d fail, %(INFRA)d infra" % c + "; total cost $%.4f" % cost)
    with open(a.report, "w") as f:
        json.dump({"model": MODEL, "total_cost_usd": cost, "counts": c, "scenarios": reps}, f, indent=2)
    print("report: " + a.report)
    if a.keep:
        print("task dirs: " + root)
    else:
        shutil.rmtree(root, ignore_errors=True)
    return 1 if c["FAIL"] else (2 if c["INFRA"] else 0)


if __name__ == "__main__":
    sys.exit(main())
