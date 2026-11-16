"""E2E journeys of docs/e2e-active-recall.md, tier cli: E-R1 to E-R8, E-R20, E-R21.

Every journey drives the real `awt` as a subprocess in a temp HOME with TZ=UTC and no AWT_*/PASEO_*/
CLAUDECODE in the environment. Fixtures are fictional (parsekit, ledgerline). E-R7 builds a 2,000-node
tree and is slow: it runs only with AWT_E2E_SLOW=1.
"""
import concurrent.futures as cf
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from test_awt import GITENV

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AWT = os.path.join(WT, "awt")
EPOCH = "1970-01-01T00:00:00Z"
QX = "gateway backoff jitter"
LIMIT_LINE = "+ tree exceeds depth 8 / 2000 nodes; deeper nodes are not covered"
DECIDE_ARGS = ("decide", "Use fixed 1 s backoff for fetch retries", "--why", "Easy to reason about for the gateway client")
ASK_ARGS = ("ask", "Is the gateway timeout a hard limit for retries?")


def clean_env(home, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AWT_", "PASEO_")) and k != "CLAUDECODE"}
    env.update(GITENV, HOME=home, TZ="UTC", GIT_CONFIG_GLOBAL="/dev/null")
    env.update(extra)
    return env


def cut(s):
    """A hit line is cut to 200 characters (SPEC.md); the cut keeps 199 and appends ~."""
    return s if len(s) <= 200 else s[:199] + "~"


def tree_hash(root):
    out = {}
    for d, dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            try:
                with open(p, "rb") as fh:
                    out[os.path.relpath(p, root)] = hashlib.sha1(fh.read()).hexdigest()
            except OSError:
                out[os.path.relpath(p, root)] = "unreadable"
    return out


def utc(ts):
    return datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")


def git_show(rev_path, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    data = subprocess.run(["git", "-C", WT, "show", rev_path], check=True, capture_output=True).stdout
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def top(root, path):
    """A node path as find and related lines print it from a cwd outside the tree: relative to the tree top."""
    return os.path.relpath(path, root)


class Cli(unittest.TestCase):
    """Temp dir T, a clean environment, and a `run` that applies the universal check U1."""

    def make_tmp(self):
        self.T = os.path.realpath(tempfile.mkdtemp(prefix="e2e-recall-"))
        self.assertNotIn(os.path.join(os.path.expanduser("~"), ".paseo"), self.T)
        self.env = clean_env(self.T)

    def cleanup(self):
        subprocess.run(["chmod", "-R", "u+rwX", self.T])
        shutil.rmtree(self.T, True)

    def run_awt(self, *args, dir=None, cwd=None, awt=AWT, py=(), expect=(0,), strict=True, **env):
        cmd = [sys.executable, *py, awt] + (["--dir", dir] if dir else []) + list(args)
        e = dict(self.env)
        for k, v in env.items():
            if v is None:
                e.pop(k, None)
            else:
                e[k] = v
        r = subprocess.run(cmd, capture_output=True, text=True, env=e, cwd=cwd or self.T)
        self.u1(r, args, strict)
        if expect is not None:
            self.assertIn(r.returncode, expect, "%s -> rc %d\n%s%s" % (args, r.returncode, r.stdout, r.stderr))
        return r

    def u1(self, r, args=(), strict=True):
        self.assertNotIn("Traceback", r.stderr, args)
        self.assertIn(r.returncode, range(5), (args, r.returncode))
        if r.returncode:
            self.assertIn("error:", r.stderr, args)
            if strict:  # FINDING F1: argparse type errors (`--limit x`) have no `fix:` line
                self.assertIn("fix:", r.stderr, args)

    def first(self, *args, **kw):
        return self.run_awt(*args, **kw).stdout.splitlines()[0].split()[0]

    def jlist(self, section, dir, **kw):
        return json.loads(self.run_awt("list", section, "--json", dir=dir, **kw).stdout)

    def rows(self, node, down=True):
        a = ["list", "--since", EPOCH] + (["--down"] if down else []) + ["--json"]
        return json.loads(self.run_awt(*a, dir=node).stdout)


class Paths:
    def __init__(self, R, T):
        self.R = R
        self.PK = R + "/workspaces/parsekit"
        self.LL = R + "/workspaces/ledgerline"
        self.RB = self.PK + "/tasks/retry-bug"
        self.GW = self.LL + "/tasks/gateway"
        self.A1 = self.RB + "/agents/a1"
        self.S1 = self.A1 + "/agents/s1"
        self.B1 = self.GW + "/agents/b1"
        self.repo = T + "/repo/parsekit"
        self.elsewhere = T + "/elsewhere"


class F1Case(Cli):
    """Fixture F1 of the spec, built once per class; each journey works on a `cp -a` copy."""

    ids = {}

    @classmethod
    def setUpClass(cls):
        c = cls("run_awt")
        c.make_tmp()
        cls.T, cls.env, cls._helper = c.T, c.env, c
        T = cls.T
        R = T + "/f1"
        os.makedirs(R)
        os.makedirs(T + "/repo/parsekit")
        os.makedirs(T + "/elsewhere")
        subprocess.run(["git", "init", "-q", T + "/repo/parsekit"], check=True, env=c.env)
        p = Paths(R, T)
        a, first = c.run_awt, c.first
        a("init", "--kind", "root", dir=R)
        a("init", "--kind", "workspace", "--name", "parsekit", dir=R)
        a("init", "--kind", "workspace", "--name", "ledgerline", dir=R)
        a("init", "--kind", "task", "--name", "main", "--goal", "Parsekit upkeep", "--done", "Nothing open", dir=p.PK)
        a("init", "--kind", "task", "--name", "retry-bug", "--goal", "Stop retry storms in the fetch client",
          "--done", "Soak test shows no synchronised retries", dir=p.PK)
        a("init", "--kind", "task", "--name", "gateway", "--goal", "Map gateway limits", "--done", "Limits documented", dir=p.LL)
        a("init", "--kind", "agent", "--name", "a1", "--key", "test:agent/a1", dir=p.RB)
        a("init", "--kind", "agent", "--name", "s1", "--key", "test:agent/s1", dir=p.A1)
        a("init", "--kind", "agent", "--name", "b1", "--key", "test:agent/b1", dir=p.GW)
        ids = cls.ids
        ids["D_RULE"] = first("decide", "Retry gateway calls with exponential backoff and full jitter", "--why",
                              "Fixed backoff synchronised the clients and overloaded the gateway", "--tag", "rule", dir=p.LL)
        ids["D_OLD"] = first("decide", "Retry every 1 s with metronome fixed backoff", "--why", "simplest", dir=p.RB)
        ids["D_NEW"] = first("decide", "Retry with capped exponential backoff", "--why", "Fixed backoff synchronised clients",
                             "--supersedes", ids["D_OLD"], dir=p.RB)
        a("ref", "https://example.invalid/backoff", "--title", "Backoff and jitter notes", "--why", "background for retry policy", dir=p.RB)
        ids["N1"] = first("note", "CI retries flaky tests twice", dir=p.PK + "/tasks/main")
        ids["Q1"] = first("ask", "Is the 30 s gateway timeout a hard limit?", dir=p.GW)
        a("answer", ids["Q1"], "Yes, the gateway enforces it", dir=p.GW)
        a("state", "--now", "Gateway timeout mapped", "--next", "Write the jitter soak test", dir=p.GW)
        a("note", " ".join(["zephyrine window"] * 15), dir=p.GW)
        a("state", "--scope", "auto", "--now", "[auto] exit=0 quillwort sweep done", "--next", "-", dir=p.A1)
        a("state", "--now", "Checked quillwort fixture", "--next", "-", dir=p.B1)

    @classmethod
    def tearDownClass(cls):
        cls._helper.cleanup()

    def setUp(self):
        self.ids = type(self).ids

    def copy(self, name, src="f1"):
        dst = os.path.join(self.T, name)
        subprocess.run(["cp", "-a", os.path.join(self.T, src), dst], check=True)
        self.addCleanup(subprocess.run, ["chmod", "-R", "u+rwX", dst])
        return dst, Paths(dst, self.T)

    def hit_lines(self, r):
        return r.stdout.splitlines()


class ER1(F1Case):
    def rule_line(self, prefix):
        return cut("%s @%s [rule]: Retry gateway calls with exponential backoff and full jitter "
                   "(why: Fixed backoff synchronised the clients and overloaded the gateway)" % (self.ids["D_RULE"], prefix))

    def test_er1_find_like_across_workspaces(self):
        R, p = self.copy("er1")
        before = tree_hash(R)
        # 1: agent vantage point, cwd outside the tree: prefixes relative to the tree top
        r1 = self.run_awt("find", "--like", QX, cwd=p.repo, AWT_DIR=p.A1)
        l1 = r1.stdout.splitlines()
        self.assertEqual(len(l1), 3, l1)
        self.assertEqual(l1[0], self.rule_line(top(R, p.LL)))
        self.assertTrue(l1[1].startswith("state @%s: " % top(R, p.GW)) and "Gateway timeout mapped" in l1[1], l1[1])
        self.assertTrue(l1[2].startswith("ref @%s: " % top(R, p.RB)) and "Backoff and jitter notes" in l1[2], l1[2])
        # 2: --dir from another cwd, identical bytes
        self.assertEqual(self.run_awt("find", "--like", QX, dir=p.A1, cwd=p.elsewhere).stdout, r1.stdout)
        # 3: from the root: relative prefixes
        l3 = self.run_awt("find", "--like", QX, cwd=R).stdout.splitlines()
        rel = ["workspaces/ledgerline", "workspaces/ledgerline/tasks/gateway", "workspaces/parsekit/tasks/retry-bug"]
        self.assertEqual(l3[0], self.rule_line(rel[0]))
        self.assertTrue(l3[1].startswith("state @%s: " % rel[1]), l3[1])
        self.assertTrue(l3[2].startswith("ref @%s: " % rel[2]), l3[2])
        self.assertEqual(len(l3), 3)
        # 4: from the retry-bug node: sibling workspace via ../, own node without prefix
        l4 = self.run_awt("find", "--like", QX, cwd=p.RB).stdout.splitlines()
        self.assertEqual(len(l4), 3, l4)
        self.assertTrue(l4[0].startswith("%s @../../../ledgerline [rule]: " % self.ids["D_RULE"]), l4[0])
        self.assertNotIn(" @", l4[2].split(":")[0])
        self.assertTrue(l4[2].startswith("ref: Backoff and jitter notes"), l4[2])
        # 5: each prefix works as --dir and holds the row
        d = self.jlist("decisions", R + "/" + rel[0], cwd=R)
        self.assertIn(self.ids["D_RULE"], [x["id"] for x in d])
        self.assertIn("Gateway timeout mapped", [x["now"] for x in self.jlist("state", rel[1], cwd=R)])
        self.assertIn("Backoff and jitter notes", [x["title"] for x in self.jlist("refs", rel[2], cwd=R)])
        # 6: only the superseded row has the word
        r = self.run_awt("find", "--like", "metronome", cwd=R)
        self.assertEqual(r.stdout, "no related records\n")
        # 7: main state surfaces, auto state does not
        l7 = self.run_awt("find", "--like", "quillwort", cwd=R).stdout.splitlines()
        self.assertEqual(len(l7), 1, l7)
        self.assertIn(" @workspaces/ledgerline/tasks/gateway/agents/b1", l7[0])
        self.assertIn("Checked quillwort fixture", l7[0])
        self.assertNotIn("agents/a1", l7[0])
        # 8: 200-char cut
        l8 = self.run_awt("find", "--like", "zephyrine", cwd=R).stdout.splitlines()
        self.assertEqual(len(l8), 1)
        self.assertLessEqual(len(l8[0]), 200)
        self.assertEqual(len(l8[0]), 200)  # the note is 425 chars, so the cut is reached
        # 9: U2
        self.assertEqual(tree_hash(R), before)


class ER2(F1Case):
    def test_er2_flags_scope_refusals(self):
        R, p = self.copy("er2")
        D = self.ids["D_RULE"]
        l = self.run_awt("find", "--like", QX, "--limit", "1", cwd=R).stdout.splitlines()
        self.assertEqual(len(l), 1)
        self.assertTrue(l[0].startswith(D + " @workspaces/ledgerline [rule]:"))
        for k in range(1, 26):
            self.run_awt("note", "gateway jitter probe %d" % k, dir=p.LL)
        self.assertEqual(len(self.run_awt("find", "--like", QX, cwd=R).stdout.splitlines()), 10)
        self.assertEqual(len(self.run_awt("find", "--like", QX, "--limit", "40", cwd=R).stdout.splitlines()), 28)
        for bad in ("0", "41", "x"):
            r = self.run_awt("find", "--like", QX, "--limit", bad, cwd=R, expect=(2,), strict=bad != "x")
            self.assertEqual(r.stdout, "", bad)
        self.run_awt("find", "gateway", "--like", QX, cwd=R, expect=(2,))
        # --limit without --like (Resolution 4)
        self.run_awt("find", "gateway", "--limit", "5", cwd=R, expect=(2,))
        # scope narrowing, from a cwd outside the tree: prefixes relative to the tree top
        down = self.run_awt("find", "--like", QX, "--down", dir=p.RB, cwd=p.elsewhere).stdout.splitlines()
        self.assertEqual(len(down), 1, down)
        self.assertTrue(down[0].startswith("ref: Backoff and jitter notes"), down[0])  # own node: no prefix
        up = self.run_awt("find", "--like", QX, "--up", dir=p.A1, cwd=p.elsewhere).stdout.splitlines()
        self.assertEqual(len(up), 1, up)
        self.assertTrue(up[0].startswith("ref @%s: Backoff and jitter notes" % top(R, p.RB)), up[0])
        # ids are kept as words (1-word query)
        self.run_awt("note", "see %s" % D, dir=p.PK)
        out = self.run_awt("find", "--like", D, cwd=R).stdout.splitlines()
        self.assertTrue(any("see " + D in x for x in out), out)
        # Q22 is deliberately not asserted: awt lists the rule row too (a row matches on its own id when the query is that id)


class ER3(F1Case):
    def test_er3_decide_related(self):
        R, p = self.copy("er3")
        ids = self.ids
        before = self.rows(R)
        r = self.run_awt(*DECIDE_ARGS, cwd=p.repo, AWT_DIR=p.A1)
        self.assertEqual(r.stderr, "")
        l = r.stdout.splitlines()
        self.assertEqual(len(l), 3, l)
        m = re.match(r"^(d-[0-9a-f]{8}) decided$", l[0])
        self.assertTrue(m, l[0])
        new1 = m.group(1)
        self.assertEqual(l[1], cut("related: %s @%s [rule]: Retry gateway calls with exponential backoff and full jitter "
                                   "(why: Fixed backoff synchronised the clients and overloaded the gateway)" % (ids["D_RULE"], top(R, p.LL))))
        self.assertEqual(l[2], cut("related: %s @%s: Retry with capped exponential backoff (why: Fixed backoff synchronised clients)"
                                   % (ids["D_NEW"], top(R, p.RB))))
        d = self.jlist("decisions", p.A1)
        row = [x for x in d if x["id"] == new1]
        self.assertEqual(len(row), 1)
        self.assertEqual(row[0]["choice"], DECIDE_ARGS[1])
        self.assertEqual(row[0]["why"], DECIDE_ARGS[3])
        after = self.rows(R)
        key = lambda x: (x["ts"], x["type"], x["id"])
        self.assertEqual([x["id"] for x in after if key(x) not in set(map(key, before))], [new1])
        self.assertNotIn(new1, " ".join(x for x in l[1:]))
        self.assertNotIn(ids["D_OLD"], " ".join(l))
        # 4: repeat verbatim
        l2 = self.run_awt(*DECIDE_ARGS, cwd=p.repo, AWT_DIR=p.A1).stdout.splitlines()
        self.assertEqual(len(l2), 4, l2)
        new2 = l2[0].split()[0]
        rel = {x.split()[1].rstrip(":") for x in l2[1:]}  # own-node lines have no @ prefix
        self.assertEqual(rel, {new1, ids["D_RULE"], ids["D_NEW"]})
        self.assertNotIn(new2, rel)


class ER4(F1Case):
    def test_er4_ask_related(self):
        R, p = self.copy("er4")
        ids = self.ids
        l = self.run_awt(*ASK_ARGS, cwd=p.repo, AWT_DIR=p.A1).stdout.splitlines()
        self.assertEqual(len(l), 3, l)
        self.assertTrue(re.match(r"^q-[0-9a-f]{8} asked$", l[0]), l[0])
        self.assertEqual(l[1], cut("related: %s @%s: Is the 30 s gateway timeout a hard limit? → Yes, the gateway enforces it"
                                   % (ids["Q1"], top(R, p.GW))))
        self.assertIn(" @" + top(R, p.GW), l[2])
        self.assertIn("Gateway timeout mapped", l[2])
        q2 = self.first("ask", "Which jitter cap applies to the soak tenants?", dir=p.B1)
        ask2 = ("ask", "What jitter cap applies to soak tenants?")
        l = self.run_awt(*ask2, cwd=p.repo, AWT_DIR=p.A1).stdout.splitlines()
        self.assertEqual(l[1], cut("related: %s @%s: Which jitter cap applies to the soak tenants?" % (q2, top(R, p.B1))))
        self.assertNotIn("→", l[1])
        self.run_awt("answer", q2, "Ten seconds", dir=p.B1)
        l = self.run_awt(*ask2, cwd=p.repo, AWT_DIR=p.A1).stdout.splitlines()
        line = [x for x in l if q2 in x][0]
        self.assertEqual(line, cut("related: %s @%s: Which jitter cap applies to the soak tenants? \u2192 Ten seconds" % (q2, top(R, p.B1))))
        self.assertIn(" \u2192 Te", line)


class ER5(F1Case):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        p = Paths(cls.T + "/f1", cls.T)
        for k in range(1, 23):
            cls._helper.run_awt("note", "Fixed backoff probe %d for the gateway" % k, dir=p.LL)

    def count_decisions(self, R):
        return len([x for x in self.rows(R) if x["type"] == "decision"])

    def test_er5_related_precedence(self):
        # (args, env, N expected or None for exit 2, warns)
        cases = [
            ((), {}, 3, False), (("--related", "1"), {}, 1, False), (("--related", "0"), {}, 0, False),
            (("--related", "20"), {}, 20, False), ((), {"AWT_RELATED": "0"}, 0, False),
            (("--related", "2"), {"AWT_RELATED": "1"}, 2, False), ((), {"AWT_RELATED": "5"}, 5, False),
            ((), {"AWT_RELATED": "abc"}, 3, True), ((), {"AWT_RELATED": "21"}, 3, True), ((), {"AWT_RELATED": "-1"}, 3, True),
            (("--related", "21"), {}, None, False), (("--related", "-1"), {}, None, False), (("--related", "x"), {}, None, False),
        ]
        for cmdname, base, hits in (("decide", DECIDE_ARGS, 24), ("ask", ASK_ARGS, 2)):
            for args, env, n, warns in cases:
                label = "%s %s %s" % (cmdname, args, env)
                with self.subTest(label):
                    R, p = self.copy("er5-%s" % abs(hash(label)), src="f1")
                    n_before = len(self.rows(R))
                    r = self.run_awt(*base, *args, cwd=p.repo, expect=(2,) if n is None else (0,),
                                     strict=args[-1:] != ("x",), **dict(env, AWT_DIR=p.A1))
                    if n is None:
                        self.assertEqual(r.stdout, "")
                        self.assertEqual(len(self.rows(R)), n_before, "a bad --related must not write a row")
                        continue
                    lines = r.stdout.splitlines()
                    self.assertEqual(len(lines), 1 + min(n, hits), (label, lines))
                    if warns:
                        self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
                        self.assertIn("AWT_RELATED", r.stderr)
                    else:
                        self.assertEqual(r.stderr, "")
                    if cmdname == "decide" and not args and not env:
                        self.assertIn(self.ids["D_RULE"], lines[1])  # rule boost puts the rule first


class IntArgsNeedFix(F1Case):
    """F1 (I3): a non-integer `--limit` / `--related` exits 2 with `error:` and a `fix:` line."""

    def test_non_integer_flag_has_fix_line(self):
        R, p = self.copy("fix1")
        for args in (("find", "--like", QX, "--limit", "x"), ASK_ARGS + ("--related", "x")):
            r = self.run_awt(*args, cwd=R, dir=p.A1, expect=(2,), strict=False)
            self.assertIn("fix:", r.stderr, args)


class ER6(F1Case):
    def test_er6_list_since(self):
        R, p = self.copy("er6")
        self.run_awt("note", "t0 marker", dir=p.RB)
        T0 = self.jlist("notes", p.RB)[-1]["ts"]
        self.run_awt("decide", "x1", "--why", "y1", dir=p.RB)
        self.run_awt("note", "a1 after", dir=p.A1)
        self.run_awt("state", "--now", "a1 now", "--next", "a1 next", dir=p.A1)
        self.run_awt("state", "--scope", "auto", "--now", "[auto] a1", "--next", "-", dir=p.A1)
        self.run_awt("note", "s1 after", dir=p.S1)
        j = lambda *a, **k: json.loads(self.run_awt(*a, **k).stdout)
        r1 = j("list", "--since", T0, "--json", dir=p.RB)
        self.assertEqual(len(r1), 2, r1)
        self.assertEqual({x["type"] for x in r1}, {"note", "decision"})
        for x in r1:
            for k in ("type", "ts", "by", "id"):
                self.assertIn(k, x)
        r2 = j("list", "--since", T0, "--down", "--json", dir=p.RB)
        self.assertEqual(len(r2), 6, r2)
        sub = [x for x in r2 if x.get("node")]
        self.assertEqual(sorted(x["node"] for x in sub),
                         sorted(["agents/a1"] * 3 + ["agents/a1/agents/s1"]))
        self.assertEqual({x["scope"] for x in r2 if x["type"] == "state"}, {"main", "auto"})
        self.assertTrue(all(x["node"] is None for x in r2 if x not in sub))
        self.assertEqual([x["ts"] for x in r2], sorted(x["ts"] for x in r2))
        r3 = j("list", "--since", T0, "--down", "--json", dir=p.A1)
        self.assertEqual(len(r3), 4, r3)
        newest = utc(max(x["ts"] for x in r2)) + datetime.timedelta(microseconds=1)
        self.assertEqual(j("list", "--since", newest.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "--down", "--json", dir=p.RB), [])
        self.run_awt("list", "--since", "yesterday", "--json", dir=p.RB, expect=(2,))
        # Resolution 6: offsets accepted, --json required, no section
        self.assertEqual(len(j("list", "--since", T0.replace("Z", "+00:00"), "--json", dir=p.RB)), 2)
        self.run_awt("list", "--since", T0, dir=p.RB, expect=(2,))
        for x in r2:
            self.assertGreaterEqual(utc(x["ts"]), utc(T0))


def build_large(c, L, awt):
    """2,000 descendants of the root (awt counts the searched top separately): 10 workspaces x 10 tasks x 18 agents (1,910) + 90 extra agents in w00/t00."""
    def a(*args, dir):
        c.run_awt(*args, dir=dir, awt=awt)
    root = L
    os.makedirs(L)
    a("init", "--kind", "root", dir=root)
    ex = cf.ThreadPoolExecutor(8)
    def pmap(fn, items):
        list(ex.map(fn, items))
    ws = ["w%02d" % i for i in range(10)]
    pmap(lambda w: a("init", "--kind", "workspace", "--name", w, dir=root), ws)
    tasks = [(w, "t%02d" % i) for w in ws for i in range(10)]
    pmap(lambda t: a("init", "--kind", "task", "--name", t[1], "--goal", "g", "--done", "d", dir="%s/workspaces/%s" % (root, t[0])), tasks)
    agents = [(w, t, "a%02d" % i) for w, t in tasks for i in range(18)] + [("w00", "t00", "a%02d" % i) for i in range(18, 108)]
    pmap(lambda x: a("init", "--kind", "agent", "--name", x[2], dir="%s/workspaces/%s/tasks/%s" % (root, x[0], x[1])), agents)
    nodes = [root] + ["%s/workspaces/%s" % (root, w) for w in ws] \
        + ["%s/workspaces/%s/tasks/%s" % (root, w, t) for w, t in tasks] \
        + ["%s/workspaces/%s/tasks/%s/agents/%s" % (root, w, t, n) for w, t, n in agents]
    assert len(nodes) == 2001, len(nodes)
    def seed(i):
        a("note", "routine note %d about the retry budget" % i, dir=nodes[i])
        if i >= 111 and (i - 111) % 10 == 0:
            a("decide", "Keep the retry budget at %d" % i, "--why", "budget", "--related", "0", dir=nodes[i])
    pmap(seed, range(len(nodes)))
    a("decide", "Shard the vellichor index by tenant", "--why", "Hot tenants starve the vellichor queue", "--tag", "rule",
      "--related", "0", dir=root + "/workspaces/w09/tasks/t09/agents/a17")
    return nodes


class ER7(Cli):
    @unittest.skipUnless(os.environ.get("AWT_E2E_SLOW") == "1", "slow: set AWT_E2E_SLOW=1 (2,000-node tree)")
    def test_er7_large_tree_timing(self):
        self.make_tmp()
        self.addCleanup(self.cleanup)
        with open(AWT, "rb") as f:
            sha = hashlib.sha1(f.read() + b"tree-v2").hexdigest()[:12]
        cache = os.path.join(tempfile.gettempdir(), "awt-e2e-large-%s.tar" % sha)
        L = self.T + "/L"
        t0 = time.perf_counter()
        if os.path.exists(cache):
            subprocess.run(["tar", "-xf", cache, "-C", self.T], check=True)
            built = "cached"
        else:
            build_large(self, L, AWT)
            subprocess.run(["tar", "-cf", cache + ".part", "-C", self.T, "L"], check=True)
            os.rename(cache + ".part", cache)
            built = "built"
        print("\n[E-R7] tree %s in %.1f s" % (built, time.perf_counter() - t0), file=sys.stderr)
        deep = "workspaces/w09/tasks/t09/agents/a17"
        def timed(*a, **kw):
            t = time.perf_counter()
            r = self.run_awt(*a, **kw)
            return r, time.perf_counter() - t
        timed("find", "--like", "vellichor index shard", cwd=L)  # warm-up
        times = []
        for _ in range(3):
            r, dt = timed("find", "--like", "vellichor index shard", cwd=L)
            times.append(dt)
            lines = r.stdout.splitlines()
            self.assertTrue(lines[0].startswith("d-") and (" @%s [rule]:" % deep) in lines[0], lines[:2])
            self.assertNotIn("tree exceeds", r.stdout)
            self.assertLess(dt, 2.0)
        r, dt2 = timed(*DECIDE_ARGS[:1], "Shard the vellichor index by region", "--why", "Region skew",
                       cwd=L, AWT_DIR=L + "/workspaces/w00/tasks/t00/agents/a00")
        self.assertLess(dt2, 2.5)
        self.assertIn("related: d-", r.stdout)
        self.assertIn(deep, r.stdout)
        self.assertNotIn("lookup stopped at 2 s", r.stdout)
        self.run_awt("init", "--kind", "agent", "--name", "extra", dir=L + "/workspaces/w00/tasks/t01")  # the 2,001st descendant
        r, dt3 = timed("find", "--like", "vellichor index shard", cwd=L)
        self.assertEqual(r.stdout.splitlines()[-1], LIMIT_LINE)
        print("[E-R7] find --like runs %s s; decide %.2f s; 2,001-node find %.2f s" %
              (", ".join("%.2f" % t for t in times), dt2, dt3), file=sys.stderr)


class ER8(F1Case):
    def corrupt(self, p, with_f=False):
        with open(p.LL + "/.awt/events.jsonl") as f:
            rule_row = [l for l in f if self.ids["D_RULE"] in l][0]
        with open(p.GW + "/.awt/events.jsonl", "ab") as f:
            f.write(b'{not json\n{"type":"decision"}\n' + b"\xff" * 16 + b"\n")
        if os.getuid() != 0:
            os.chmod(p.PK + "/tasks/main/.awt/events.jsonl", 0)
        os.makedirs(p.LL + "/tasks/broken/.awt/events.jsonl")
        os.makedirs(p.PK + "/tasks/.new-zz/.awt")
        with open(p.PK + "/tasks/.new-zz/.awt/events.jsonl", "w") as f:
            f.write(rule_row)
        os.symlink(p.R, p.PK + "/tasks/loop")
        if with_f and os.getuid() != 0:
            os.chmod(p.LL + "/tasks", 0)

    def quarantined(self, r):
        m = re.search(r"(\d+) quarantined rows", r.stdout)
        self.assertTrue(m, r.stdout)
        return int(m.group(1))

    def steps_1_2(self, R, p, tolerate_missing=False):
        r = self.run_awt("find", "--like", QX, cwd=R)
        out = r.stdout
        for bad in (".new-zz", "broken", "/loop", "loop/"):
            self.assertNotIn(bad, out)
        if not tolerate_missing:
            self.assertEqual(out.count(self.ids["D_RULE"]), 1, out)
            self.assertIn("Gateway timeout mapped", out)
        r = self.run_awt(*DECIDE_ARGS, cwd=p.repo, AWT_DIR=p.A1)
        l = r.stdout.splitlines()
        self.assertTrue(re.match(r"^d-[0-9a-f]{8} decided$", l[0]), l)
        self.assertIn(l[0].split()[0], [x["id"] for x in self.jlist("decisions", p.A1)])

    def test_er8_corrupt_nodes(self):
        pre = git_show("a35fea8:awt", self.T + "/pre/awt")
        R, p = self.copy("er8")
        self.corrupt(p)
        self.steps_1_2(R, p)
        R2, p2 = self.copy("er8-base")
        self.corrupt(p2)
        mine = self.quarantined(self.run_awt("doctor", dir=p.GW))
        base = self.quarantined(self.run_awt("doctor", dir=p2.GW, awt=pre))
        self.assertEqual(mine, base)
        self.assertGreaterEqual(mine, 3)
        # f): an unreadable tasks directory under a workspace
        if os.getuid() != 0:
            R3, p3 = self.copy("er8-f")
            self.corrupt(p3, with_f=True)
            self.steps_1_2(R3, p3, tolerate_missing=True)


class ER21(F1Case):
    def test_er21_stdlib_only(self):
        R, p = self.copy("er21")
        plain = self.run_awt("--help", cwd=self.T)
        iso = self.run_awt("--help", cwd=self.T, py=("-I", "-S"))
        self.assertEqual(iso.stdout, plain.stdout)
        a = self.run_awt("find", "--like", QX, cwd=R)
        b = self.run_awt("find", "--like", QX, cwd=R, py=("-I", "-S"))
        self.assertEqual(b.stdout, a.stdout)
        self.assertEqual(len(b.stdout.splitlines()), 3)
        py39 = shutil.which("python3.9")
        if py39:
            for args in (("find", "--like", QX), ("decide", *DECIDE_ARGS[1:])):
                R9, p9 = self.copy("er21-39-%s" % args[0])
                ref = self.run_awt(*args, cwd=p9.repo if args[0] == "decide" else R9, AWT_DIR=p9.A1 if args[0] == "decide" else None)
                R9b, p9b = self.copy("er21-39b-%s" % args[0])
                cmd = [py39, AWT, *args]
                r = subprocess.run(cmd, capture_output=True, text=True, cwd=p9b.repo if args[0] == "decide" else R9b,
                                   env=dict(self.env, **({"AWT_DIR": p9b.A1} if args[0] == "decide" else {})))
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(len(r.stdout.splitlines()), len(ref.stdout.splitlines()))


SNAP = {
    "projects": [{"id": "prj_0001", "name": "parsekit", "path": "/tmp/parsekit"}],
    "workspaces": [
        {"id": "wks_0001", "projectId": "prj_0001", "project": "parsekit", "name": "parsekit", "cwd": "/tmp/parsekit", "archived": False},
        {"id": "wks_0002", "projectId": "prj_0001", "project": "parsekit", "name": "ledgerline", "cwd": "/tmp/ledgerline", "archived": True},
    ],
    "agents": [
        {"id": "agt_0001", "name": "Plan parser", "provider": "claude", "model": "sonnet", "cwd": "/tmp/parsekit",
         "workspaceId": "wks_0001", "parentAgentId": None, "archived": True, "background": False},
        {"id": "agt_0002", "name": "Map gateway", "provider": "claude", "model": "sonnet", "cwd": "/tmp/ledgerline",
         "workspaceId": "wks_0002", "parentAgentId": None, "archived": False, "background": False},
        {"id": "agt_0003", "name": "Read RFC", "provider": "claude", "model": "sonnet", "cwd": "/tmp/parsekit",
         "workspaceId": "wks_0001", "parentAgentId": "agt_0001", "archived": False, "background": False},
    ],
}
SECTIONS = ("refs", "decisions", "questions", "effects", "notes", "state")


class ER20(Cli):
    def test_er20_upgrade_from_v020(self):
        self.make_tmp()
        self.addCleanup(self.cleanup)
        T = self.T
        v020 = git_show("v0.2.0:awt", T + "/v020/awt")
        mig = git_show("v0.2.0:migrate-paseo", T + "/v020/migrate-paseo")
        pre = git_show("a35fea8:awt", T + "/pre/awt")
        snap = T + "/snap.json"
        with open(snap, "w") as f:
            json.dump(SNAP, f)
        R = T + "/root"
        os.makedirs(R)
        v = lambda *a, **k: self.run_awt(*a, awt=v020, **k)
        v("init", "--kind", "root", dir=R)
        r = subprocess.run([sys.executable, mig, R, "--from", snap], capture_output=True, text=True, env=self.env, cwd=T)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        nodes = {n["key"]: R + "/" + n["path"] for n in json.loads(v("list", "nodes", "--all", "--json", dir=R).stdout)}
        statuses = {n["key"]: n["status"] for n in json.loads(v("list", "nodes", "--all", "--json", dir=R).stdout)}
        self.assertEqual(statuses["paseo:workspace/wks_0002"], "done")
        self.assertEqual(statuses["paseo:agent/agt_0001"], "done")
        ws1, ws2 = nodes["paseo:workspace/wks_0001"], nodes["paseo:workspace/wks_0002"]
        task1 = nodes["paseo:task/wks_0001/imported"]
        ag1, ag2 = nodes["paseo:agent/agt_0001"], nodes["paseo:agent/agt_0002"]
        rule = "Retry gateway calls with exponential backoff and full jitter"
        v("decide", rule, "--why", "Fixed backoff synchronised the clients and overloaded the gateway", "--tag", "rule", dir=task1)
        q = v("ask", "Is the 30 s gateway timeout a hard limit?", dir=task1).stdout.split()[0]
        v("answer", q, "Yes, the gateway enforces it", dir=task1)
        v("note", "CI retries flaky tests twice", dir=task1)
        v("note", "Soak run queued for Monday", dir=task1)
        v("state", "--now", "Parsekit imported", "--next", "Review notes", dir=ws1)
        v("state", "--now", "Ledgerline archived", "--next", "-", dir=ws2)
        autos = []
        for n in (ag1, ag2):
            r = v("state", "--scope", "auto", "--now", "[auto] exit=0 quillwort sweep", "--next", "-", dir=n, expect=None)
            autos.append(r.returncode)
            if r.returncode:  # v0.2.0 refused: write with the pre-feature awt and record it
                self.run_awt("state", "--scope", "auto", "--now", "[auto] exit=0 quillwort sweep", "--next", "-", dir=n, awt=pre)
        print("\n[E-R20] v0.2.0 auto-state write exit codes: %s" % autos, file=sys.stderr)
        solo = T + "/solo"
        os.makedirs(solo)
        v("init", "--goal", "Solo parsekit chore", "--done", "Chore done", dir=solo)
        v("decide", "Pin the parser version", "--why", "reproducible", dir=solo)
        sq = v("ask", "Which parser version?", dir=solo).stdout.split()[0]
        v("answer", sq, "Version two", dir=solo)
        v("note", "solo note", dir=solo)
        v("state", "--now", "solo now", "--next", "solo next", dir=solo)
        v("ref", "https://example.invalid/solo", "--title", "Solo ref", "--why", "context", dir=solo)

        # 1: pre-feature awt and this awt give identical output on every node and on solo
        # v2 phase 2 writes BRIEF.md in every node; the pre-feature awt would grep it as an ordinary file, so compare without them
        for top in (R, solo):
            for dp, _, fns in os.walk(top):
                if "BRIEF.md" in fns:
                    os.unlink(os.path.join(dp, "BRIEF.md"))
        before = tree_hash(R), tree_hash(solo)
        targets = list(nodes.values()) + [R, solo]
        cmds = [("resume",), ("resume", "--json"), ("list", "nodes", "--all", "--json")] + [("list", s, "--json") for s in SECTIONS] \
            + [("find", "--tree", "quillwort"), ("doctor",)]
        jobs = [(n, c) for n in targets for c in cmds]
        def both(job):
            n, c = job
            a = self.run_awt(*c, dir=n, awt=pre, expect=None)
            b = self.run_awt(*c, dir=n)
            return job, a, b
        with cf.ThreadPoolExecutor(8) as ex:
            for job, a, b in ex.map(both, jobs):
                if job[1] == ("doctor",):  # v2 phase 0 changes doctor's effect and settings checks on purpose
                    self.assertEqual(b.returncode, a.returncode, job)
                else:
                    self.assertEqual((b.returncode, b.stdout, b.stderr), (a.returncode, a.stdout, a.stderr), job)
                if job[1] == ("doctor",):
                    self.assertIn("0 quarantined", b.stdout)
        # 2: solo resume, v0.2.0 vs now
        self.assertEqual(v("resume", dir=solo).stdout, self.run_awt("resume", dir=solo).stdout)
        # 3: auto states never surface
        r = self.run_awt("find", "--like", "quillwort", cwd=R)
        self.assertEqual(r.stdout, "no related records\n")
        # 5: records in done nodes are candidates
        l = self.run_awt("find", "--like", rule, cwd=R).stdout.splitlines()
        self.assertTrue(any(x.startswith("d-") and "[rule]" in x for x in l), l)
        # 6 (U2 for 1-3, 5)
        self.assertEqual((tree_hash(R), tree_hash(solo)), before)
        # 4: decide in agt_0002 prints no related line
        r = self.run_awt("decide", "Quillwort sweep cadence", "--why", "quillwort runs nightly", cwd=T, AWT_DIR=ag2)
        self.assertEqual(len(r.stdout.splitlines()), 1, r.stdout)
        self.assertTrue(r.stdout.endswith("decided\n"))
        # the write also creates the agent's and its task's BRIEF.md (v2 phase 2); no other file appears
        self.assertEqual({k for k in tree_hash(R) if not k.endswith("BRIEF.md")}, set(before[0]))
        # 7: auto rows appear in list --since with scope auto
        oldest = min(x["ts"] for x in self.rows(R))
        rows = json.loads(self.run_awt("list", "--since", oldest, "--down", "--json", dir=R).stdout)
        self.assertEqual(len([x for x in rows if x["type"] == "state" and x["scope"] == "auto"]), 2)


if __name__ == "__main__":
    unittest.main()
