#!/usr/bin/env python3
"""Scripted chaos test for awt. Stdlib only. Everything happens in temp dirs.

  python3 tests/chaos.py [--quick] [--seed N] [--only SUBSTR] [--keep]

--quick: under ~30 s (CI). Default: a few minutes. Exit 1 on any broken invariant.
Each attack prints one line; a failure prints the seed and the commands that reproduce it.
Secret-shaped strings are built at runtime so this file contains none.
"""
import argparse, concurrent.futures as cf, datetime, json, os, random, re, shlex, shutil, signal, socket, subprocess, sys, tempfile, threading, time, zlib

HERE = os.path.dirname(os.path.realpath(__file__))
AWT = os.path.join(os.path.dirname(HERE), "awt")
HOST = socket.gethostname()
TRACE = "Traceback (most recent call last)"
IDRX = re.compile(r"\b[dqen]-[0-9a-f]{8}\b")
SEC = {
    "aws": "AK" + "IA" + "ABCDEFGHIJKLMNOP",
    "gh": "gh" + "p_" + "a" * 36,
    "pat": "github" + "_pat_" + "A1" * 10,
    "slack": "xo" + "xb-" + "1234567890ab",
    "sk": "s" + "k-" + "a" * 24,
    "pk": "-----BEGIN " + "RSA PRIVATE KEY" + "-----",
    "jwt": "ey" + "J" + "a" * 12 + ".ey" + "J" + "b" * 12 + "." + "c" * 12,
}
SECRE = [re.compile(p) for p in (
    r"AKIA[0-9A-Z]{16}", r"gh[pousr]_[A-Za-z0-9]{36,}", r"github_pat_[A-Za-z0-9_]{20,}", r"xox[abprs]-[A-Za-z0-9-]{10,}",
    r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")]
SECTIONS = ["refs", "context", "docs", "outbox", "misc", "decisions", "questions", "effects", "notes", "state"]


def iso(off=0):
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=off)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def cnt(p):
    try:
        with open(p, "rb") as g:
            return len(g.read().split(b"\n")) - 1
    except OSError:
        return 0


def q(a):
    if isinstance(a, bytes):
        a = a.decode("utf-8", "backslashreplace")
    return shlex.quote(a if len(a) < 160 else a[:60] + "...<%d chars>" % len(a))


def wait_for(cond, timeout=10, step=0.02):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


class R:
    def __init__(s, rc, ob, eb, dt, hung):
        s.rc, s.outb, s.errb, s.dt, s.hung = rc, ob, eb, dt, hung
        s.out, s.err = ob.decode("utf-8", "replace"), eb.decode("utf-8", "replace")


class Ctx:
    def __init__(s, name, base, seed, quick):
        s.name, s.base, s.quick = name, base, quick
        s.rng = random.Random(zlib.crc32(name.encode()) ^ seed)
        s.cmds, s.fails, s.notes, s.lock, s.n, s.skipped = [], [], [], threading.Lock(), 0, None
        os.makedirs(base)
        s.home = os.path.join(base, "home")
        os.makedirs(s.home)

    def fail(s, msg):
        with s.lock:
            if msg not in s.fails and len(s.fails) < 8:
                s.fails.append(msg)

    def note(s, msg):
        with s.lock:
            s.notes.append(msg)

    def log(s, line):
        with s.lock:
            s.cmds.append(line)
            del s.cmds[:-30]

    def path(s, *a):
        return os.path.join(s.base, *a)

    def nxt(s):
        with s.lock:
            s.n += 1
            return s.n

    def env(s, **over):
        e = {k: v for k, v in os.environ.items() if k in ("PATH", "TMPDIR", "LANG", "LC_ALL")}
        e.update(HOME=s.home, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="c", GIT_AUTHOR_EMAIL="c@x",
                 GIT_COMMITTER_NAME="c", GIT_COMMITTER_EMAIL="c@x", PYTHONDONTWRITEBYTECODE="1", GIT_TERMINAL_PROMPT="0")
        for k, v in over.items():
            if v is None:
                e.pop(k, None)
            else:
                e[k] = v
        return e

    def check(s, r, args, allow=(0, 1, 2, 3, 4), what=""):
        d = what or " ".join(q(a) for a in (args or [])[:6])
        if r.hung:
            s.fail("HANG (> timeout): awt %s" % d)
            return
        if TRACE in r.err or TRACE in r.out:
            tail = [x for x in r.err.splitlines() if x.strip()][-1:] or ["?"]
            s.fail("python traceback: awt %s -> %s" % (d, tail[0][:160]))
        if r.rc not in allow:
            s.fail("exit code %s not in spec (0-4): awt %s" % (r.rc, d))
        if args:
            verbs = [a for a in args if isinstance(a, str) and not a.startswith("-")]
            if (args[:1] == ["resume"] or (verbs and verbs[0] == "resume")) and "--json" not in args:
                lim = 5200 if s.name.startswith("tree-") else 4400
                if len(r.out) > lim:
                    s.fail("brief is %d chars (> %d): awt %s" % (len(r.out), lim, d))
                if "--hook" in args and r.rc != 0:
                    s.fail("resume --hook exited %d" % r.rc)
            if r.rc in (1, 3, 4) and r.err and verbs[:1] != ["doctor"] and verbs[:1] != ["save"] and "error:" not in r.err:
                s.fail("refusal without 'error:' line: awt %s -> %s" % (d, r.err[:100]))
            if r.rc in (1, 4) and r.err and "error:" in r.err and "fix:" not in r.err:
                s.fail("refusal without 'fix:' line: awt %s -> %s" % (d, r.err.strip()[:100]))

    def raw(s, argv, cwd=None, env=None, stdin=None, timeout=None, args=None, allow=(0, 1, 2, 3, 4), check=True, label=None):
        timeout = timeout or (30 if s.quick else 90)
        s.log("(cd %s && %s)" % (q(cwd or "."), label or " ".join(q(a) for a in argv)))
        t0 = time.time()
        p = subprocess.Popen(argv, cwd=cwd, env=env if env is not None else s.env(), stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        hung = False
        try:
            ob, eb = p.communicate(stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            hung = True
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                ob, eb = p.communicate(timeout=5)
            except Exception:
                ob = eb = b""
        r = R(p.returncode, ob, eb, time.time() - t0, hung)
        if check:
            s.check(r, args, allow, label)
        return r

    def sh(s, argv, cwd=None, env=None):
        return s.raw(argv, cwd=cwd, env=env, check=False, timeout=120)

    def git(s, cwd, *a):
        return s.sh(["git", "-C", cwd] + list(a))

    def finish(s, p, args, timeout=60, allow=(0, 1, 2, 3, 4)):
        hung = False
        try:
            p.wait(timeout)
        except subprocess.TimeoutExpired:
            hung = True
            p.kill()
            p.wait()
        p._o.close()
        with open(p._o.name, "rb") as g:
            b = g.read()
        r = R(p.returncode, b, b, 0, hung)
        s.check(r, args, allow)
        return r


class Task:
    def __init__(s, ctx, name="t", init=True):
        s.ctx = ctx
        s.dir = os.path.realpath(ctx.path(name))
        os.makedirs(s.dir, exist_ok=True)
        s.awt = os.path.join(s.dir, "awt")
        shutil.copy(AWT, s.awt)
        os.chmod(s.awt, 0o755)
        s.ev = os.path.join(s.dir, ".awt", "events.jsonl")
        if init:
            s.run("init", "--goal", "chaos goal", "--done", "chaos done")

    def p(s, *a):
        return os.path.join(s.dir, *a)

    def run(s, *a, **k):
        cwd = k.pop("cwd", s.dir)
        return s.ctx.raw([s.awt] + list(a), cwd=cwd, args=list(a), **k)

    def popen(s, *a, env=None):
        n = s.ctx.nxt()
        so = open(s.ctx.path("po%d.out" % n), "wb")
        s.ctx.log("(cd %s && %s &)" % (q(s.dir), " ".join(q(x) for x in ("./awt",) + a)))
        p = subprocess.Popen([s.awt] + list(a), cwd=s.dir, env=env or s.ctx.env(), stdin=subprocess.DEVNULL, stdout=so, stderr=so, start_new_session=True)
        p._o = so
        return p

    def id(s, *a, **k):
        m = IDRX.search(s.run(*a, **k).out)
        return m.group(0) if m else None

    def plan(s, target, run=None, body=None, extra=()):
        a = ["effect", "plan", "--target", target] + (["--run", run] if run else []) + (["--body", body] if body else []) + list(extra)
        r = s.run(*a)
        m = re.match(r"(e-[0-9a-f]{8})", r.out)
        return (m.group(1) if m else None), r

    def state(s, eid):
        m = re.search(r"^state: (\w+)", s.run("effect", "show", eid).out, re.M)
        return m.group(1) if m else None

    def append(s, b):
        with open(s.ev, "ab") as f:
            f.write(b)

    def forge(s, typ, **f):
        row = dict(v=1, ts=iso(), type=typ, host=HOST, by="forge")
        row.update(f)
        s.append((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))

    def effrows(s):
        n = 0
        for ln in open(s.ev, "rb").read().split(b"\n"):
            try:
                r = json.loads(ln)
                n += r.get("type") == "effect" and r.get("step") == "planned" and r.get("attempt", 1) == 1
            except Exception:
                pass
        return n

    def sane(s, label="", need_ok=True):
        out = {}
        for k, a in (("resume", ["resume"]), ("list", ["list"]), ("find", ["find", "chaos"]), ("hook", ["resume", "--hook"])):
            r = out[k] = s.run(*a)
            if (need_ok or k == "hook") and r.rc != 0:
                s.ctx.fail("%s: awt %s exited %d: %s" % (label, " ".join(a), r.rc, r.err.strip()[:160]))
        s.run("doctor")
        return out


def put(t, nm, data):
    """Write context/<nm>; APFS refuses non-UTF-8 names, so on macOS skip just that file."""
    try:
        with open(os.path.join(os.fsencode(t.dir), b"context", nm), "wb") as f:
            f.write(data)
    except OSError:
        if sys.platform != "darwin":
            raise


def escape(t, eid):
    """Is there a legal way out of whatever state the effect is in?"""
    st = t.state(eid)
    if st == "claimed":
        wait_for(lambda: t.state(eid) != "claimed", 5, 0.2)
        st = t.state(eid)
    if st in ("sent", "dropped"):
        return True
    if st in ("unknown", "conflict"):
        if t.run("effect", "mark", eid, "not-sent").rc:
            return False
        st = t.state(eid)
    if st == "planned":
        return t.run("effect", "mark", eid, "dropped").rc == 0 and t.state(eid) == "dropped"
    return False


def audit(c, t, strict=True):
    """Every line awt itself wrote is valid, <= 4096 bytes, has no secret text; ids unique."""
    try:
        raw = open(t.ev, "rb").read()
    except OSError:
        return
    seen = set()
    for n, ln in enumerate(raw.split(b"\n"), 1):
        if not ln.strip():
            continue
        if strict:
            if len(ln) + 1 > 4096:
                c.fail("events.jsonl line %d is %d bytes (> 4096)" % (n, len(ln) + 1))
            try:
                r = json.loads(ln.decode("utf-8"))
            except Exception:
                c.fail("events.jsonl line %d is not valid JSON/UTF-8: %r" % (n, ln[:80]))
                continue
            if not re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$", str(r.get("ts"))):
                c.fail("bad ts on line %d: %r" % (n, r.get("ts")))
            if r.get("type") in ("note", "decision", "question") or (r.get("type") == "effect" and r.get("step") == "planned" and r.get("attempt", 1) == 1):
                if r["id"] in seen:
                    c.fail("duplicate id %s" % r["id"])
                seen.add(r["id"])
        txt = ln.decode("utf-8", "replace")
        for rx in SECRE:
            if rx.search(txt):
                c.fail("secret text in events.jsonl line %d (%s)" % (n, rx.pattern[:12]))
                break


ATTACKS = []


def attack(name, solo=False):
    def d(f):
        ATTACKS.append((name, f, solo))
        return f
    return d


# ---------------------------------------------------------------- fuzz
def hostile(r, huge):
    pool = ["", " ", "   ", "\t\n", "x", "a" * huge, "é" * 5000, "日本語テキスト", "שלום עולם מה שלומך", "\u202eevil\u202c", "👨‍👩‍👧‍👦" * 60,
            "line1\nline2\r\nline3", "\x1b[31mred\x1b[0m", "'\"`", "$(touch CANARY)", "`touch CANARY`", "; touch CANARY #", "| touch CANARY",
            "&& touch CANARY", ">CANARY", "*", "?", "~", "$HOME", "%s%n%x{0}{}", "-x", "--", "---", "--help", "-h", "-", "--dir", "--by",
            "--version", "--again", "--now", "d-7f3a9c21", "q-00000000", "e-deadbeef", "n-", "d-ffffffff", "D-7F3A9C21", "../../etc/passwd",
            "/etc/passwd", "outbox/../../x", "docs/", ".", "..", "null", "{}", "[1]", '{"a":1}', "\ufeffbom", "\x7f", "a\u0301" * 300,
            "\U0010ffff", b"\xff\xfe", b"\xc3\x28", b"\xed\xa0\x80", SEC["aws"], "x " + SEC["gh"] + " y", SEC["pk"], SEC["jwt"], "sk-short",
            "9" * 400, "-1", "99999999999999999999", "slack:#eng", "https://x.atlassian.net/browse/T-1", "T-1"]
    return r.choice(pool)


@attack("fuzz")
def a_fuzz(c):
    t = Task(c)
    ids, targets, lk = {"d": [], "q": [], "e": [], "n": []}, {}, threading.Lock()
    huge = 20000 if c.quick else 100000
    open(t.p("outbox", "b.md"), "w").write("body\n")
    N = 150 if c.quick else 900

    def job(i):
        r = random.Random(c.rng.random() * 0 + i * 7919 + zlib.crc32(b"fz"))
        A = lambda: hostile(r, huge)

        def ID(k):
            with lk:
                l = ids[k]
                return r.choice(l) if l and r.random() < .7 else A() if r.random() < .5 else "%s-%08x" % (k, r.getrandbits(32))
        opt = lambda *x: list(x) if r.random() < .5 else []
        stdin, env = None, None
        runs = ["true", "echo hi", "exit 3", "sleep 0.05", "false"]
        v = r.randrange(26)
        if v == 0: a = ["note", A()]
        elif v == 1: a = ["ask", A()]
        elif v == 2: a = ["answer", ID("q"), A()]
        elif v == 3: a = ["decide", A(), "--why", A()] + opt("--supersedes", ID("d")) + opt("--tag", A())
        elif v == 4: a = ["state", "--now", A(), "--next", A()] + opt("--scope", A())
        elif v == 5: a = ["ref", A(), "--title", A()] + opt("--kind", A()) + opt("--no-access") + opt("--why", A())
        elif v == 6:
            a = ["capture", "--from", A(), "--title", A()] + opt("--ref", A()) + r.choice([[], ["-"], [A()]])
            stdin = r.choice([b"", b"hello\n", b"\x00\x01binary\xff", os.urandom(3000), b"x" * 300000, SEC["aws"].encode() + b" body", "é日本😀\n".encode() * 100, b" \n "])
        elif v == 7: a = ["supersede", A(), A()] + opt("--why", A())
        elif v == 8: a = ["status", r.choice(["active", "paused", "done", A()])]
        elif v == 9: a = ["list", r.choice(SECTIONS + [A()])] + opt("--all")
        elif v == 10: a = ["find", A()]
        elif v == 11: a = ["effect", "plan", "--target", A(), r.choice(["--body", "--run"]), r.choice(["outbox/b.md", A()] if False else ["outbox/b.md"]) if False else "outbox/b.md"]
        elif v == 12: a = ["effect", "plan", "--target", r.choice(["slack:#a", "slack:#b", A()]), "--run", r.choice(runs)] + opt("--class", r.choice(["additive", "overwrite", A()])) + opt("--again") + opt("--snapshot", r.choice(["echo s", "true"])) + opt("--verify", r.choice(["true", "false"])) + opt("--after", ID("e")) + opt("--why", A())
        elif v == 13: a = ["effect", "show", ID("e")]
        elif v == 14:
            e = ID("e")
            a = ["effect", "apply", e, "--target", targets.get(e, A())] + opt("--timeout", r.choice(["1", "0", "-3", "abc", "99999999999999999999"]))
        elif v == 15: a = ["effect", "mark", ID("e"), r.choice(["sent", "not-sent", "dropped", A()])] + opt("--ref", A()) + opt("--why", A())
        elif v == 16: a = ["doctor"]
        elif v == 17: a = ["save", A()]
        elif v == 18: a = ["resume"] + opt("--hook")
        elif v == 19: a = ["init", "--goal", A(), "--done", A()]
        elif v == 20: a = ["help", A()]
        elif v == 21: a = [A()] + opt(A())
        elif v == 22: a = ["--by", A(), "note", "by-fuzz"]
        elif v == 23: a = ["--dir", A(), "note", "dir-fuzz"]
        elif v == 24:
            a, env = ["note", "env-by"], c.env(AWT_BY=A() if isinstance(A(), str) else "x")
        else: a = ["effect"] + opt(A())
        res = t.run(*a, stdin=stdin, env=env, timeout=60)
        m = IDRX.findall(res.out)
        with lk:
            for x in m:
                ids[x[0]].append(x)
            if a[:2] == ["effect", "plan"] and m and "--target" in a:
                targets[m[0]] = a[a.index("--target") + 1]
    with cf.ThreadPoolExecutor(8) as ex:
        list(ex.map(job, range(N)))
    if os.path.exists(t.p("CANARY")):
        c.fail("shell metacharacters in an argument were executed (CANARY created)")
    audit(c, t)
    t.sane("after fuzz")
    d = t.run("doctor")
    m = re.search(r"(\d+) quarantined", d.out)
    if m and int(m.group(1)):
        c.fail("awt itself wrote %s rows that its own reader quarantines" % m.group(1))


# ---------------------------------------------------------------- effects
def ctr(c):
    return c.path("ctr%d" % c.nxt())


@attack("effect-race-apply")
def a_race(c):
    t = Task(c)
    C = ctr(c)
    for rnd in range(1 if c.quick else 3):
        tgt = "slack:#r%d" % rnd
        eid, _ = t.plan(tgt, run="echo x >> %s; sleep 1" % shlex.quote(C))
        with cf.ThreadPoolExecutor(24) as ex:
            rs = list(ex.map(lambda _: t.run("effect", "apply", eid, "--target", tgt), range(24)))
        if cnt(C) != rnd + 1:
            c.fail("round %d: sender ran %d times for one effect (want exactly 1)" % (rnd, cnt(C) - rnd))
        if sum(r.rc == 0 for r in rs) != 1:
            c.fail("round %d: %d applies succeeded (want 1)" % (rnd, sum(r.rc == 0 for r in rs)))
        t.run("effect", "apply", eid, "--target", tgt)
        if cnt(C) != rnd + 1:
            c.fail("apply after sent ran the sender again")
        if t.state(eid) != "sent":
            c.fail("state after race is %s, not sent" % t.state(eid))
    audit(c, t)


@attack("effect-kill-before-claim")
def a_kill_snap(c):
    t = Task(c)
    C, F = ctr(c), c.path("flag")
    snap = "if [ -e %s ]; then echo snap; else sleep 20; echo snap; fi" % shlex.quote(F)
    eid, _ = t.plan("jira:K-1", run="echo x >> %s" % shlex.quote(C), extra=["--snapshot", snap])
    p = t.popen("effect", "apply", eid, "--target", "jira:K-1")
    time.sleep(.7)
    p.kill()
    p.wait()
    if cnt(C) or t.state(eid) != "planned":
        c.fail("killed before claim: counter=%d state=%s (want 0, planned)" % (cnt(C), t.state(eid)))
    open(F, "w").close()
    r = t.run("effect", "apply", eid, "--target", "jira:K-1")
    if r.rc or cnt(C) != 1:
        c.fail("apply after pre-claim kill: rc=%d counter=%d" % (r.rc, cnt(C)))


@attack("effect-kill-during-run")
def a_kill_run(c):
    t = Task(c)
    C = ctr(c)
    open(t.p("outbox", "a.md"), "w").write("a\n")
    open(t.p("outbox", "b.md"), "w").write("b\n")
    eid, _ = t.plan("slack:#k", run="echo x >> %s; sleep 3" % shlex.quote(C), body="outbox/a.md")
    p = t.popen("effect", "apply", eid, "--target", "slack:#k")
    wait_for(lambda: cnt(C) == 1, 10)
    p.kill()
    p.wait()
    st = t.state(eid)
    if st != "unknown":
        c.fail("apply killed mid-run: state is %s (want unknown)" % st)
    time.sleep(3.3)
    if t.run("effect", "apply", eid, "--target", "slack:#k").rc == 0 or cnt(C) != 1:
        c.fail("applying an unknown effect ran the sender again (counter=%d)" % cnt(C))
    e2, _ = t.plan("slack:#k", run="echo x >> %s; sleep 3" % shlex.quote(C), body="outbox/a.md")
    if e2 != eid:
        c.fail("repeat plan of same key gave %s, want %s" % (e2, eid))
    if t.plan("slack:#k", run="echo y >> %s" % shlex.quote(C), body="outbox/b.md")[1].rc == 0:
        c.fail("reworded plan accepted on a target with an unknown effect")
    if t.run("status", "done").rc == 0:
        c.fail("status done accepted with an unknown effect")
    if t.run("effect", "mark", eid, "not-sent").rc:
        c.fail("cannot mark an unknown effect not-sent")
    open(t.p("outbox", "a.md"), "w").write("a\n")
    r = t.run("effect", "apply", eid, "--target", "slack:#k")
    if r.rc or cnt(C) != 2:
        c.fail("deliberate second attempt: rc=%d counter=%d (want 2)" % (r.rc, cnt(C)))
    audit(c, t)


@attack("effect-kill-after-run")
def a_kill_verify(c):
    t = Task(c)
    C, F = ctr(c), c.path("flag")
    eid, _ = t.plan("slack:#v", run="echo x >> %s" % shlex.quote(C), extra=["--verify", "if [ -e %s ]; then true; else sleep 20; fi" % shlex.quote(F)])
    p = t.popen("effect", "apply", eid, "--target", "slack:#v")
    wait_for(lambda: cnt(C) == 1, 10)
    time.sleep(.2)
    p.kill()
    p.wait()
    if t.state(eid) != "unknown":
        c.fail("killed after run, before outcome row: state %s (want unknown)" % t.state(eid))
    if t.run("effect", "apply", eid, "--target", "slack:#v").rc == 0 or cnt(C) != 1:
        c.fail("second send after kill between run and outcome")
    open(F, "w").close()
    if not escape(t, eid):
        c.fail("no legal way out of effect state")


@attack("effect-kill-random")
def a_kill_rand(c):
    t = Task(c)
    for i in range(7 if c.quick else 45):
        C = ctr(c)
        tgt = "slack:#x%d" % i
        eid, _ = t.plan(tgt, run="echo x >> %s" % shlex.quote(C))
        p = t.popen("effect", "apply", eid, "--target", tgt)
        time.sleep(c.rng.uniform(0, .15))
        p.kill()
        p.wait()
        time.sleep(.25)
        n, st = cnt(C), t.state(eid)
        if n > 1:
            c.fail("sender ran %d times for one attempt" % n)
        if n >= 1 and st == "planned":
            c.fail("sender ran (counter=%d) but effect %s is planned: a second apply would resend" % (n, eid))
        if st == "planned":
            t.run("effect", "apply", eid, "--target", tgt)
            if cnt(C) != 1:
                c.fail("after pre-claim kill, re-apply produced counter=%d" % cnt(C))
        elif not escape(t, eid):
            c.fail("effect %s stuck in %s with no legal way out" % (eid, st))
    audit(c, t)


@attack("effect-exit-nonzero")
def a_nz(c):
    t = Task(c)
    C = ctr(c)
    open(t.p("outbox", "a.md"), "w").write("a\n")
    eid, _ = t.plan("slack:#nz", run="echo x >> %s; exit 3" % shlex.quote(C), body="outbox/a.md")
    r = t.run("effect", "apply", eid, "--target", "slack:#nz")
    if r.rc != 1 or t.state(eid) != "unknown" or cnt(C) != 1:
        c.fail("non-zero sender: rc=%d state=%s counter=%d (want 1, unknown, 1)" % (r.rc, t.state(eid), cnt(C)))
    t.run("effect", "apply", eid, "--target", "slack:#nz")
    if cnt(C) != 1:
        c.fail("unknown effect was retried")
    e2, r2 = t.plan("slack:#nz", run="echo x >> %s; exit 3" % shlex.quote(C), body="outbox/a.md")
    if e2 != eid or r2.rc:
        c.fail("repeat plan after unknown: %r rc=%d" % (e2, r2.rc))
    if t.plan("slack:#nz", body="outbox/a.md")[1].rc == 0:
        c.fail("manual plan accepted on target with unknown effect, no --again")
    e3, r3 = t.plan("slack:#nz", run="echo x >> %s; exit 3" % shlex.quote(C), body="outbox/a.md", extra=["--again"])
    if not e3 or e3 == eid:
        c.fail("--again did not create a new effect")
    else:
        t.run("effect", "apply", e3, "--target", "slack:#nz")
        if cnt(C) != 2:
            c.fail("--again: counter %d (want 2)" % cnt(C))
    for e in (eid, e3):
        if e and not escape(t, e):
            c.fail("stuck: %s" % e)
    audit(c, t)


@attack("effect-timeout")
def a_to(c):
    t = Task(c)
    C = ctr(c)
    eid, _ = t.plan("slack:#to", run="echo x >> %s; sleep 3; echo y >> %s" % ((shlex.quote(C),) * 2))
    r = t.run("effect", "apply", eid, "--target", "slack:#to", "--timeout", "1")
    if r.dt > 15:
        c.fail("--timeout 1 took %.1fs" % r.dt)
    if t.state(eid) != "unknown" or r.rc != 1:
        c.fail("timeout: rc=%d state=%s (want 1, unknown)" % (r.rc, t.state(eid)))
    time.sleep(3.5)
    if cnt(C) != 1:
        c.fail("timed-out sender kept running (counter=%d, want 1)" % cnt(C))
    r = t.run("effect", "apply", eid, "--target", "slack:#to", "--timeout", "0")
    if cnt(C) != 1:
        c.fail("unknown effect re-run with --timeout 0")


@attack("effect-snapshot-timeout")
def a_snap_to(c):
    t = Task(c)
    C = ctr(c)
    eid, _ = t.plan("slack:#st", run="echo x >> %s" % shlex.quote(C), extra=["--snapshot", "sleep 30; echo s"])
    r = t.run("effect", "apply", eid, "--target", "slack:#st", "--timeout", "1")
    if r.dt > 15:
        c.fail("snapshot ignored --timeout (%.0fs)" % r.dt)
    if cnt(C) or t.state(eid) not in ("planned",):
        c.fail("snapshot timeout consumed the effect: counter=%d state=%s" % (cnt(C), t.state(eid)))


@attack("effect-snapshot-empty-verify-fail")
def a_snap_empty(c):
    t = Task(c)
    C = ctr(c)
    eid, _ = t.plan("slack:#se", run="echo x >> %s" % shlex.quote(C), extra=["--snapshot", "true"])
    r = t.run("effect", "apply", eid, "--target", "slack:#se")
    if r.rc != 1 or cnt(C) or t.state(eid) != "planned" or os.listdir(t.p(".awt", "claims")):
        c.fail("empty snapshot: rc=%d counter=%d state=%s claims=%s" % (r.rc, cnt(C), t.state(eid), os.listdir(t.p(".awt", "claims"))))
    e2, _ = t.plan("slack:#vf", run="echo x >> %s" % shlex.quote(C), extra=["--verify", "false"])
    r = t.run("effect", "apply", e2, "--target", "slack:#vf")
    if r.rc != 1 or t.state(e2) != "unknown" or cnt(C) != 1:
        c.fail("failing verify: rc=%d state=%s counter=%d" % (r.rc, t.state(e2), cnt(C)))
    if t.plan("slack:#ow", run="true", extra=["--class", "overwrite"])[1].rc != 1:
        c.fail("overwrite without --snapshot accepted")


@attack("effect-plan-repeat-race")
def a_plan_rep(c):
    t = Task(c)
    open(t.p("outbox", "a.md"), "w").write("a\n")
    ids = {t.plan("slack:#pr", body="outbox/a.md")[0] for _ in range(5)}
    if len(ids) != 1 or t.effrows() != 1:
        c.fail("5 sequential identical plans made %d effects" % t.effrows())
    with cf.ThreadPoolExecutor(16) as ex:
        res = list(ex.map(lambda _: t.plan("slack:#pr2", run="echo hi", body="outbox/a.md")[0], range(16)))
    n = t.effrows() - 1
    if n != 1 or len(set(res)) != 1:
        c.fail("16 concurrent identical plans created %d effects (%d distinct ids); same key must write nothing" % (n, len(set(res))))
    audit(c, t)


@attack("effect-mark-inflight")
def a_inflight(c):
    t = Task(c)
    C = ctr(c)
    eid, _ = t.plan("slack:#mf", run="echo x >> %s; sleep 2" % shlex.quote(C))
    p = t.popen("effect", "apply", eid, "--target", "slack:#mf")
    wait_for(lambda: cnt(C) == 1, 10)
    for to in ("sent", "not-sent", "dropped"):
        if t.run("effect", "mark", eid, to).rc == 0:
            c.fail("mark %s accepted while the sender is in flight" % to)
    t.ctx.finish(p, ["apply"])
    if t.state(eid) != "sent" or cnt(C) != 1:
        c.fail("after in-flight marks: state=%s counter=%d" % (t.state(eid), cnt(C)))


@attack("effect-drop-during-snapshot")
def a_drop_snap(c):
    t = Task(c)
    C = ctr(c)
    eid, _ = t.plan("slack:#ds", run="echo x >> %s" % shlex.quote(C), extra=["--snapshot", "sleep 2; echo snap"])
    p = t.popen("effect", "apply", eid, "--target", "slack:#ds")
    time.sleep(.8)
    r = t.run("effect", "mark", eid, "dropped")
    t.ctx.finish(p, ["apply"])
    if r.rc == 0 and cnt(C):
        c.fail("effect %s was marked dropped (acknowledged) while apply was snapshotting, then apply SENT it anyway (counter=%d). state now: %s" % (eid, cnt(C), t.state(eid)))


@attack("effect-legality")
def a_legal(c):
    t = Task(c)
    C = ctr(c)
    for n in "ab":
        open(t.p("outbox", n + ".md"), "w").write(n + "\n")
    e, _ = t.plan("t:run", run="echo x >> %s" % shlex.quote(C))
    for to in ("sent", "not-sent"):
        if t.run("effect", "mark", e, to).rc == 0:
            c.fail("mark %s accepted from planned on a run effect" % to)
    if t.run("effect", "apply", e, "--target", "t:other").rc == 0 or cnt(C):
        c.fail("apply with the wrong --target ran")
    if t.run("effect", "apply", "e-00000000", "--target", "x").rc != 4:
        c.fail("apply unknown id: want exit 4")
    if t.run("effect", "show", "e-00000000").rc != 4:
        c.fail("show unknown id: want exit 4")
    if t.run("effect", "plan", "--target", "x").rc != 2:
        c.fail("plan with neither --body nor --run: want exit 2")
    if t.run("effect", "plan", "--target", "x", "--body", "outbox").rc == 0:
        c.fail("plan --body directory accepted")
    if t.run("effect", "plan", "--target", "x" * 201, "--run", "true").rc == 0:
        c.fail("201-char target accepted")
    if t.run("effect", "plan", "--target", "x", "--run", "true", "--after", "e-00000000").rc != 4:
        c.fail("plan --after unknown id: want exit 4")
    m, _ = t.plan("t:man", body="outbox/a.md")
    ra = t.run("effect", "apply", m, "--target", "t:man")
    if ra.rc == 0 or "outbox/a.md" not in (ra.out + ra.err) or "mark" not in (ra.out + ra.err):
        c.fail("apply on a manual effect must refuse and print body path + mark command")
    # body changed after plan
    b, _ = t.plan("t:body", run="echo x >> %s" % shlex.quote(C), body="outbox/b.md")
    open(t.p("outbox", "b.md"), "w").write("changed\n")
    if t.run("effect", "apply", b, "--target", "t:body").rc == 0 or cnt(C):
        c.fail("apply ran after body changed")
    # after
    a2, _ = t.plan("t:after", run="echo x >> %s" % shlex.quote(C), extra=["--after", m])
    if t.run("effect", "apply", a2, "--target", "t:after").rc == 0 or cnt(C):
        c.fail("apply ran while --after effect is not sent")
    if t.run("status", "done").rc == 0:
        c.fail("status done accepted with planned effects")
    if t.run("effect", "mark", m, "sent", "--ref", "http://x").rc:
        c.fail("manual mark sent refused")
    if t.run("effect", "apply", a2, "--target", "t:after").rc or cnt(C) != 1:
        c.fail("apply after prerequisite sent failed")
    for to in ("sent", "dropped", "not-sent"):
        if t.run("effect", "mark", m, to).rc == 0:
            c.fail("mark %s accepted from sent" % to)
    d, _ = t.plan("t:drop", body="outbox/a.md", extra=["--why", "again"])
    t.run("effect", "mark", d, "dropped")
    r = t.plan("t:drop", body="outbox/a.md")[1]
    if r.rc != 1 or "--again" not in r.err:
        c.fail("re-plan of dropped effect: want refusal with --again fix, got rc=%d %s" % (r.rc, r.err[:80]))
    for e2 in (e, b):
        t.run("effect", "mark", e2, "dropped")
    if t.run("status", "done").rc != 0:
        c.fail("status done refused after all effects resolved: %s" % t.run("status", "done").err[:120])


@attack("effect-crash-gap-conflict-stuck")
def a_gap(c):
    t = Task(c)
    C = ctr(c)
    # crash between claim file and claimed row
    e, _ = t.plan("g:1", run="echo x >> %s" % shlex.quote(C))
    key = re.search(r"^key: (\w+)", t.run("effect", "show", e).out, re.M).group(1)
    open(t.p(".awt", "claims", key + ".1"), "w").close()
    if t.state(e) != "unknown":
        c.fail("claim file with no claimed row should read unknown, got %s" % t.state(e))
    if t.run("effect", "apply", e, "--target", "g:1").rc == 0 or cnt(C):
        c.fail("apply ran after crash between claim and claimed row")
    if not escape(t, e):
        c.fail("no legal way out after claim-file crash")
    # conflict
    e, _ = t.plan("g:2", run="echo x >> %s" % shlex.quote(C))
    for _ in range(2):
        t.forge("effect", id=e, step="claimed", attempt=1, pid=2 ** 22 + 77)
    if t.state(e) != "conflict" or "conflict" not in t.run("resume").out:
        c.fail("two claimed rows for one attempt: state=%s (brief must show conflict)" % t.state(e))
    if not escape(t, e):
        c.fail("no legal way out of conflict")
    # recycled pid: claimed by a pid that is alive but is not awt
    e, _ = t.plan("g:3", run="echo x >> %s" % shlex.quote(C))
    sl = subprocess.Popen(["sleep", "600"])
    try:
        # a claim older than its timeout plus margin is no longer in flight, even though the pid is alive
        t.forge("effect", id=e, step="claimed", attempt=1, pid=sl.pid, ts=iso(-3600), timeout=5)
        ok = escape(t, e)
        if not ok:
            c.fail("effect %s is 'claimed' by a dead apply whose pid was reused by another live process: mark, apply and status done are all refused forever (no legal way out)" % e)
    finally:
        sl.kill()
        sl.wait()


# ---------------------------------------------------------------- log damage
def seed(t):
    ids = [t.id("note", "seed note %d" % i) for i in range(4)]
    ids += [t.id("ask", "seed question?"), t.id("decide", "seed choice", "--why", "because", "--tag", "rule")]
    t.run("state", "--now", "seed now", "--next", "seed next")
    t.run("ref", "https://example.com/x", "--title", "seed ref")
    open(t.p("outbox", "seed.md"), "w").write("seed\n")
    C = ctr(t.ctx)
    m, _ = t.plan("manual:t", body="outbox/seed.md")
    r, _ = t.plan("slack:#run", run="echo x >> %s" % shlex.quote(C))
    t.run("capture", "--from", "slack", "--title", "seed cap", stdin=b"captured text\n")
    ids += [m, r]
    t.id("note", "SACRIFICE row last")
    return ids, r, C


def rd(t):
    return open(t.ev, "rb").read()


def wr(t, b):
    open(t.ev, "wb").write(b)


def dmg_trunc(t): wr(t, rd(t)[:-25])
def dmg_utf8(t): t.append(b'{"v":1,"type":"note","text":"\xc3')
def dmg_garbage(t): t.append(b"garbage\n{{{\n[1,2]\nnull\n123\n\"str\"\n{}\n{\"type\":\"note\"}\n{\"type\":\"bogus\",\"ts\":\"x\"}\n")
def dmg_binary(t): t.append(bytes(random.Random(1).getrandbits(8) for _ in range(60000)) + b"\n")
def dmg_nul(t): t.append(b"\0" * 5000 + b"\n" + b"\0\n")
def dmg_nonl(t): wr(t, rd(t).rstrip(b"\n"))
def dmg_big(t): t.append(b"A" * 10_000_000 + b"\n")
def dmg_bigvalid(t): t.append(b'{"v":1,"ts":"2020-01-01T00:00:00.000000Z","type":"note","id":"n-aaaaaaaa","text":"' + b"B" * 10_000_000 + b'"}\n')
def dmg_recursion(t): t.append(b"[" * 300000 + b"\n" + b'{"a":' * 200000 + b"\n")
def dmg_delete(t): os.unlink(t.ev)
def dmg_surrogate(t): t.append(b'{"v":1,"ts":"2020-01-01T00:00:00.000000Z","type":"note","id":"n-bbbbbbbb","text":"\\ud800 lone"}\n')


def dmg_dir(t):
    os.unlink(t.ev)
    os.mkdir(t.ev)


def dmg_symlink(t):
    ext = t.ctx.path("ext.jsonl")
    shutil.move(t.ev, ext)
    os.symlink(ext, t.ev)


def dmg_dup(t): t.append(rd(t))


def dmg_forged(t):
    for st, extra in (("sent", {}), ("claimed", {}), ("planned", {"attempt": 9}), ("dropped", {})):
        t.forge("effect", id="e-ffffffff", step=st, **extra)
    for ln in rd(t).split(b"\n"):
        try:
            r = json.loads(ln)
        except Exception:
            continue
        if r.get("type") == "effect" and r.get("run"):
            for st, n in (("sent", 1), ("unknown", 1), ("planned", 5), ("claimed", 3), ("sent", 2)):
                t.forge("effect", id=r["id"], step=st, attempt=n)
            t.forge("effect", id=r["id"], step="planned", attempt=1, target="other", key="zz", run="echo evil")


def dmg_skew(t):
    out = []
    for ln in rd(t).split(b"\n"):
        try:
            r = json.loads(ln)
            if r.get("type") == "effect" and r.get("run"):
                r["ts"] = iso(3600)
            ln = json.dumps(r, ensure_ascii=False).encode()
        except Exception:
            pass
        out.append(ln)
    wr(t, b"\n".join(out))
    t.forge("state", now="from 1970", next="n", scope="old", **{}) if False else None
    t.append((json.dumps(dict(v=1, ts="1970-01-01T00:00:00.000000Z", type="state", host=HOST, by="x", now="epoch", next="n", scope="epoch")) + "\n").encode())
    t.append((json.dumps(dict(v=1, ts="2999-12-31T23:59:59.999999Z", type="note", host=HOST, by="x", id="n-cccccccc", text="far future")) + "\n").encode())
    t.append((json.dumps(dict(v=1, ts="0001-01-01T00:00:00.000000Z", type="note", host=HOST, by="x", id="n-dddddddd", text="year one")) + "\n").encode())


def dmg_types(t):
    base = dict(v=1, ts=iso(), host=HOST, by="x")
    rows = [dict(base, type="effect", id="e-11111111", step="planned", target=["a"], key="k1", run="true"),
            dict(base, type="effect", id="e-22222222", step="planned", target=5, key="k2", body=["x"], run=7),
            dict(base, type="effect", id="e-33333333", step="planned", target="t", key=9, after=5, attempt=True),
            dict(base, type="decision", id="d-11111111", choice="c", why="w", tags=[1, {"a": 1}, None]),
            dict(base, type="decision", id="d-22222222", choice="c", why="w", tags="rule", supersedes=["x"]),
            dict(base, type="ref", target="t", title="t", kind="repo", access="ok", path=5, branch=None),
            dict(base, type="ref", target="t2", title="t", kind="repo", access="ok", path="/nonexistent", branch=7, host=5),
            dict(base, type="state", now="n", next="n", scope=["x"]),
            dict(base, type="capture", path=["p"], **{"from": "f"}, title="t", sha="s"),
            dict(base, type="note", id="n-eeeeeeee", text="x", ts=5), dict(base, type="note", id=["n"], text="x"),
            dict(base, type="question", id="q-11111111", text="x" * 5000), dict(base, type="answer", ref=["q"], text="t"),
            dict(base, type="task", goal="g\n" * 5000, done_means="d" * 100000), dict(base, type="status", status="bogus"),
            dict(base, type="state", now="n" * 100000, next="x", scope="s" * 100000)]
    t.append(b"".join((json.dumps(r) + "\n").encode() for r in rows))


for _n, _f, _keep, _strict in (("trunc-mid-row", dmg_trunc, True, True), ("partial-utf8-tail", dmg_utf8, True, True), ("garbage-rows", dmg_garbage, True, True),
                               ("binary", dmg_binary, True, True), ("nul-bytes", dmg_nul, True, True), ("no-trailing-newline", dmg_nonl, True, True),
                               ("10mb-line", dmg_big, True, True), ("10mb-valid-note", dmg_bigvalid, True, True), ("deep-json-recursion", dmg_recursion, True, True),
                               ("lone-surrogate-row", dmg_surrogate, True, True), ("delete-file", dmg_delete, False, True), ("file-is-directory", dmg_dir, False, False),
                               ("symlinked-file", dmg_symlink, True, True), ("duplicate-rows", dmg_dup, True, True), ("forged-illegal-effects", dmg_forged, True, True),
                               ("clock-skew", dmg_skew, True, True), ("type-confusion", dmg_types, True, True)):
    def _mk(name, fn, keep, strict):
        @attack("log-" + name)
        def a(c):
            t = Task(c)
            ids, reff, C = seed(t)
            before = t.run("list").out
            fn(t)
            out = t.sane(name, need_ok=strict)
            if keep:
                miss = [i for i in ids if i not in out["list"].out]
                if miss:
                    c.fail("rows lost after '%s': %s" % (name, miss))
            if name in ("garbage-rows", "binary", "nul-bytes", "10mb-line", "deep-json-recursion", "lone-surrogate-row", "type-confusion", "forged-illegal-effects") and "quarantine" not in out["resume"].out and out["resume"].rc == 0:
                c.fail("damaged rows not reported as quarantined in the brief")
            if name == "file-is-directory":
                if t.run("note", "x").rc == 0:
                    pass
                return
            n = t.id("note", "after damage %s" % name)
            if not n:
                c.fail("write refused after '%s'" % name)
            elif n not in t.run("list", "notes").out:
                c.fail("write after '%s' acknowledged but not visible (torn tail not healed?)" % name)
            if keep and name not in ("forged-illegal-effects", "clock-skew"):
                r = t.run("effect", "apply", reff, "--target", "slack:#run")
                if r.rc or cnt(C) != 1 or t.state(reff) != "sent":
                    c.fail("effect apply after '%s': rc=%d counter=%d state=%s: %s" % (name, r.rc, cnt(C), t.state(reff), r.err.strip()[:100]))
            if name == "clock-skew":
                r = t.run("effect", "apply", reff, "--target", "slack:#run")
                if r.rc == 0 and t.state(reff) != "sent":
                    c.fail("apply acknowledged 'sent' but state reads %s: planned row has a future ts, so claimed/sent rows sort before it and are quarantined" % t.state(reff))
                if cnt(C) > 1:
                    c.fail("counter %d" % cnt(C))
            if name == "forged-illegal-effects":
                if t.state(reff) != "planned":
                    c.fail("forged illegal transitions changed state of a real effect to %s" % t.state(reff))
                else:
                    t.run("effect", "apply", reff, "--target", "slack:#run")
                    if cnt(C) != 1:
                        c.fail("apply after forged rows: counter=%d" % cnt(C))
    _mk(_n, _f, _keep, _strict)


@attack("log-future-timestamp-pins-state")
def a_future(c):
    t = Task(c)
    t.forge("status", status="paused", ts="2999-01-01T00:00:00.000000Z")
    t.forge("state", scope="main", now="future state", next="n", ts="2999-01-01T00:00:00.000000Z")
    t.run("status", "active")
    t.run("state", "--now", "real handoff after skew", "--next", "n")
    o = t.run("resume").out
    if "real handoff after skew" not in o or "Status: active" not in o:
        c.fail("acknowledged status/state writes are shadowed forever by one row with a future ts (brief still shows paused / old state)")


@attack("log-concurrent-damage")
def a_cdmg(c):
    t = Task(c)
    seed(t)
    acked, stop, lk = [], threading.Event(), threading.Lock()

    def w(k):
        i = 0
        while not stop.is_set():
            i += 1
            n = t.id("note", "w%d-%d" % (k, i))
            if n:
                with lk:
                    acked.append(n)
    th = [threading.Thread(target=w, args=(k,)) for k in range(6)]
    [x.start() for x in th]
    end = time.time() + (2.5 if c.quick else 8)
    while time.time() < end:
        t.append(b"garbage line\n" + os.urandom(40).replace(b"\n", b"") + b"\n")
        t.run("resume")
        t.run("list", "notes")
        time.sleep(.05)
    stop.set()
    [x.join() for x in th]
    o = t.run("list", "notes").out
    miss = [n for n in acked if n not in o]
    if miss:
        c.fail("%d of %d acknowledged writes missing while garbage rows were being appended" % (len(miss), len(acked)))
    if len(set(acked)) != len(acked):
        c.fail("duplicate ids")
    t.sane("after concurrent damage")


# ---------------------------------------------------------------- environment
@attack("env-read-only")
def a_ro(c):
    if os.geteuid() == 0:
        c.skipped = "root"
        return
    t = Task(c)
    open(t.p("docs", "a.md"), "w").write("a\n")
    open(t.p("docs", "b.md"), "w").write("b\n")
    open(t.p("outbox", "o.md"), "w").write("o\n")
    C = ctr(c)
    e, _ = t.plan("ro:1", run="echo x >> %s" % shlex.quote(C))
    t.run("note", "pre")
    os.chmod(t.ev, 0o444)
    ds = [t.dir] + [t.p(d) for d in ("context", "docs", "outbox", "misc", ".awt", ".awt/claims", ".awt/blobs", ".awt/runs")]
    for d in ds:
        os.chmod(d, 0o555)
    try:
        cases = [["note", "x"], ["ask", "x"], ["state", "--now", "a", "--next", "b"], ["decide", "c", "--why", "w"], ["ref", "http://x", "--title", "t"],
                 ["capture", "--from", "s", "--title", "t"], ["supersede", "docs/a.md", "docs/b.md"], ["status", "paused"],
                 ["effect", "plan", "--target", "ro:2", "--body", "outbox/o.md"], ["effect", "apply", e, "--target", "ro:1"], ["init", "--goal", "g2", "--done", "d2"]]
        for a in cases:
            r = t.run(*a, stdin=b"body" if a[0] == "capture" else None)
            if r.rc != 3:
                c.fail("read-only: awt %s exited %d (want 3): %s" % (" ".join(a[:3]), r.rc, (r.err or r.out).strip()[:100]))
            elif "awt" not in r.err or "run" not in r.err:
                c.fail("exit 3 did not print the exact command to rerun: %r" % r.err[:100])
        if cnt(C):
            c.fail("sender ran although nothing could be recorded (counter=%d)" % cnt(C))
        for a in (["resume"], ["list"], ["find", "x"], ["resume", "--hook"]):
            if t.run(*a).rc:
                c.fail("read-only: %s failed" % a[0])
    finally:
        for d in ds:
            os.chmod(d, 0o755)
        os.chmod(t.ev, 0o644)


@attack("env-missing-dirs")
def a_missing(c):
    t = Task(c)
    C = ctr(c)
    for d in ("claims", "blobs", "runs"):
        shutil.rmtree(t.p(".awt", d))
    e, _ = t.plan("md:1", run="echo x >> %s" % shlex.quote(C), extra=["--snapshot", "echo s"])
    r = t.run("effect", "apply", e, "--target", "md:1")
    if r.rc or cnt(C) != 1:
        c.fail("apply with missing .awt/claims: rc=%d counter=%d" % (r.rc, cnt(C)))
    os.unlink(t.ev)
    t.sane("no events file")
    shutil.rmtree(t.p(".awt"))
    r = t.run("resume")
    if r.rc != 4 or "fix: ./awt init" not in r.err:
        c.fail("no .awt: want exit 4 + 'fix: ./awt init', got %d %r" % (r.rc, r.err[:80]))
    if t.run("resume", "--hook").rc or t.run("resume", "--hook").out:
        c.fail("resume --hook with no task must exit 0 and print nothing")
    shutil.copy(AWT, c.path("loose"))
    os.chmod(c.path("loose"), 0o755)
    r = c.raw([c.path("loose"), "note", "x"], cwd=c.base, args=["note", "x"])
    if r.rc != 4:
        c.fail("script outside a task: want exit 4, got %d" % r.rc)


@attack("env-no-git-no-home")
def a_nogit(c):
    t = Task(c)
    bin_ = c.path("bin")
    os.makedirs(bin_)
    os.symlink(sys.executable, os.path.join(bin_, "python3"))
    os.symlink("/bin/sh", os.path.join(bin_, "sh"))
    g = c.path("repo")
    subprocess.run(["git", "init", "-q", g], env=c.env(), capture_output=True)
    subprocess.run(["git", "-C", g, "commit", "-q", "--allow-empty", "-m", "i"], env=c.env(), capture_output=True)
    t.run("ref", g, "--title", "repo")
    t.run("state", "--now", "n", "--next", "n")
    for label, env in (("no git on PATH", c.env(PATH=bin_)), ("HOME unset", c.env(HOME=None)), ("both", c.env(PATH=bin_, HOME=None))):
        for a in (["resume"], ["resume", "--hook"], ["list"], ["find", "x"], ["doctor"], ["note", "n %s" % label], ["ref", g, "--title", "r2"]):
            r = t.run(*a, env=env)
            if a[0] in ("resume", "list", "find", "note") and r.rc:
                c.fail("%s: awt %s exited %d: %s" % (label, a[0], r.rc, r.err.strip()[:100]))
        if label != "HOME unset":
            r = t.run("save", "m", env=env)
            if r.rc not in (1,) or "error:" not in r.err:
                c.fail("%s: save should refuse cleanly (rc 1 + error:), got rc=%d %r" % (label, r.rc, r.err[:100]))
        b = t.run("resume", env=env).out
        if label != "HOME unset" and "git unavailable" not in b and "repo" not in b:
            c.fail("%s: brief shows no degraded git line for the repo ref" % label)


@attack("env-cwd-deleted-subdir-symlink-other-task")
def a_cwd(c):
    t = Task(c, "A")
    u = Task(c, "B")
    wrap = 'mkdir g && cd g && rmdir ../g && exec "$@"'
    for a in (["resume"], ["list"], ["note", "gone"], ["find", "x"], ["doctor"]):
        r = c.raw(["sh", "-c", wrap, "sh", t.awt] + a, cwd=c.base, args=a)
        if a[0] != "doctor" and r.rc:
            c.fail("cwd deleted (script in task): awt %s exited %d: %s" % (a[0], r.rc, r.err.strip()[:100]))
    loose = c.path("loosebin")
    os.makedirs(loose)
    shutil.copy(AWT, os.path.join(loose, "awt"))
    os.chmod(os.path.join(loose, "awt"), 0o755)
    lawt = os.path.join(loose, "awt")
    for a in (["resume"], ["note", "x"], ["init", "--goal", "g", "--done", "d"]):
        r = c.raw(["sh", "-c", wrap, "sh", lawt] + a, cwd=c.base, args=a)
        if a[0] == "init":
            continue
        if r.rc != 4:
            c.fail("cwd deleted, no task: awt %s should exit 4, got %d: %s" % (a[0], r.rc, r.err.strip()[:100]))
    r = c.raw(["sh", "-c", wrap, "sh", lawt, "resume", "--hook"], cwd=c.base, args=["resume", "--hook"])
    # subdir walk-up via loose script
    sub = t.p("docs", "x", "y")
    os.makedirs(sub)
    r = c.raw([lawt, "note", "from subdir"], cwd=sub, args=["note"])
    if r.rc or "from subdir" not in t.run("list", "notes").out:
        c.fail("walk-up from a subdirectory failed: rc=%d %s" % (r.rc, r.err[:100]))
    # script in A, cwd in B: script dir wins
    r = c.raw([t.awt, "note", "script-dir-wins"], cwd=u.dir, args=["note"])
    if "script-dir-wins" not in t.run("list", "notes").out or "script-dir-wins" in u.run("list", "notes").out:
        c.fail("script dir should win over cwd's task")
    # symlinked script
    ln = c.path("lnbin", "awt")
    os.makedirs(os.path.dirname(ln))
    os.symlink(t.awt, ln)
    r = c.raw([ln, "note", "via-symlink"], cwd=os.path.dirname(ln), args=["note"])
    if r.rc or "via-symlink" not in t.run("list", "notes").out:
        c.fail("symlink to script: rc=%d %s" % (r.rc, r.err[:100]))
    # --dir and AWT_DIR precedence
    r = c.raw([ln, "--dir", u.dir, "note", "to-b"], cwd=c.base, args=["note"])
    r = c.raw([ln, "note", "to-b2"], cwd=c.base, args=["note"], env=c.env(AWT_DIR=u.dir))
    o = u.run("list", "notes").out
    if "to-b" not in o or "to-b2" not in o:
        c.fail("--dir / AWT_DIR ignored")
    r = c.raw([ln, "--dir", c.path("nonexistent"), "note", "x"], cwd=c.base, args=["note"])
    if r.rc != 4:
        c.fail("--dir to a non-task: want exit 4, got %d" % r.rc)


@attack("env-malicious-modules")
def a_mod(c):
    t = Task(c)
    mark = c.path("PWNED")
    code = "import os as _o\nopen(%r,'a').write(__name__+'\\n')\nraise SystemExit(77)\n" % mark
    code = "open(%r,'a').write(__name__+'\\n')\nraise SystemExit(77)\n" % mark
    other = c.path("cwd_evil")
    os.makedirs(other)
    for m in ("json", "os", "re", "subprocess", "hashlib", "argparse", "datetime", "socket", "shlex", "signal", "time", "sys"):
        for d in (t.dir, other):
            open(os.path.join(d, m + ".py"), "w").write(code)
    for d in (t.dir, other):
        open(os.path.join(d, "sitecustomize.py"), "w").write(code)
    for cwd in (t.dir, other):
        for a in (["resume"], ["note", "mod"], ["list"], ["doctor"], ["find", "x"]):
            r = t.run(*a, cwd=cwd)
            if r.rc == 77 or os.path.exists(mark):
                c.fail("malicious module beside the script or in cwd was imported (rc=%d)" % r.rc)
                return
    r = c.raw([sys.executable, t.awt, "resume"], cwd=other, args=["resume"])
    if os.path.exists(mark):
        c.fail("malicious module imported via 'python3 awt'")


@attack("env-weird-files", solo=False)
def a_files(c):
    t = Task(c)
    # symlink loop
    os.symlink("../docs", t.p("docs", "loop"))
    os.symlink("self", t.p("docs", "self"))
    os.symlink(t.p("docs"), t.p("misc", "tolink"))
    os.symlink("/nonexistent", t.p("docs", "dangling"))
    # FIFOs and unreadable files
    os.mkfifo(t.p("context", "pipe"))
    os.mkfifo(t.p("misc", "pipe2"))
    os.mkfifo(t.p("topfifo"))
    open(t.p("context", "locked.txt"), "w").write("secret chaosterm\n")
    os.chmod(t.p("context", "locked.txt"), 0)
    os.makedirs(t.p("misc", "lockeddir"))
    open(t.p("misc", "lockeddir", "f"), "w").write("x")
    os.chmod(t.p("misc", "lockeddir"), 0)
    open(t.p("docs", "ok.md"), "w").write("# Fine chaosterm\n")
    for nm in (b"\xff\xfe.txt", b"caf\xe9.md", b"\xed\xa0\x80"):
        put(t, nm, b"latin \xe9 chaosterm\n")
    try:
        for a in (["resume"], ["list"], ["list", "context"], ["list", "misc"], ["list", "--all"], ["find", "chaosterm"], ["resume", "--hook"], ["doctor"]):
            r = t.run(*a, timeout=15)
            if r.rc and a[0] != "doctor":
                c.fail("awt %s exited %d with FIFOs/unreadable files present: %s" % (" ".join(a), r.rc, r.err.strip()[:100]))
        if "docs/ok.md" not in t.run("list", "docs", timeout=15).out:
            c.fail("healthy file missing from listing next to hostile ones")
    finally:
        os.chmod(t.p("context", "locked.txt"), 0o644)
        os.chmod(t.p("misc", "lockeddir"), 0o755)


def mk_locale(name, env_over):
    @attack("env-locale-" + name)
    def a(c):
        t = Task(c)
        for nm in (b"\xff\xfe.txt", "日本語.md".encode()):
            put(t, nm, "# héllo 日本語\n".encode())
        env = c.env(**env_over)
        for a_ in (["note", "héllo 日本語 😀"], ["state", "--now", "日本語 ✓", "--next", "é"], ["decide", "ünï", "--why", "😀"], ["list"], ["find", "日本語"], ["resume"], ["resume", "--hook"],
                   ["ref", "https://x.com/é", "--title", "ü"], ["effect", "plan", "--target", "slack:#é", "--run", "true"]):
            r = t.run(*a_, env=env)
            if r.rc and a_[0] != "find":
                c.fail("locale %s: awt %s exited %d: %s" % (name, a_[0], r.rc, r.err.strip()[:120]))
        r = t.run("save", "ü", env=env)
    return a


mk_locale("C-no-coercion", dict(LC_ALL="C", LANG="C", PYTHONCOERCECLOCALE="0", PYTHONUTF8="0"))
mk_locale("latin1", dict(LC_ALL="en_US.ISO8859-1", LANG="en_US.ISO8859-1", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0"))


@attack("env-100k-files", solo=True)
def a_many(c):
    t = Task(c)
    n = 4000 if c.quick else 100000
    d = t.p("misc")
    for i in range(n):
        os.close(os.open(os.path.join(d, "f%06d.txt" % i), os.O_WRONLY | os.O_CREAT))
    t.run("state", "--now", "n", "--next", "n")
    for a in (["resume"], ["resume", "--hook"], ["list", "misc"], ["find", "zzz-nothing"], ["list"]):
        r = t.run(*a, timeout=100)
        if r.rc:
            c.fail("awt %s with %d files in misc/ exited %d" % (a[0], n, r.rc))
        if a[0] == "resume" and r.dt > (10 if c.quick else 30):
            c.fail("resume took %.1fs with %d files (runs at every session start)" % (r.dt, n))


@attack("env-1gb-sparse", solo=True)
def a_sparse(c):
    t = Task(c)
    for p in ("misc/big.bin", "context/big.txt"):
        with open(t.p(p), "wb") as f:
            f.truncate(1 << 30)
    for a in (["resume"], ["list"], ["find", "x"], ["doctor"]):
        r = t.run(*a, timeout=60)
        if r.rc and a[0] != "doctor":
            c.fail("awt %s with a 1 GB sparse file exited %d" % (a[0], r.rc))
        if r.dt > 30:
            c.fail("awt %s took %.0fs with a 1 GB sparse file" % (a[0], r.dt))


# ---------------------------------------------------------------- path escape
def snapdir(p):
    out = {}
    for dp, dns, fns in os.walk(p):
        for n in fns + dns:
            f = os.path.join(dp, n)
            out[f] = os.lstat(f).st_size if not os.path.isdir(f) else -1
    return out


@attack("path-escape")
def a_esc(c):
    t = Task(c)
    out = c.path("outside")
    os.makedirs(out)
    open(os.path.join(out, "x.md"), "w").write("outside\n")
    open(os.path.join(out, "a.md"), "w").write("outside a\n")
    os.symlink("../../outside/x.md", t.p("outbox", "ln.md"))
    os.symlink(out, t.p("outbox", "dl"))
    os.symlink(out, t.p("docs", "dl"))
    os.symlink(os.path.join(out, "a.md"), t.p("docs", "lna.md"))
    open(t.p("docs", "old.md"), "w").write("old\n")
    open(t.p("docs", "new.md"), "w").write("new\n")
    for b in ("../outside/x.md", os.path.join(out, "x.md"), "outbox/../../outside/x.md", "outbox/ln.md", "outbox/dl/x.md", "/etc/hosts", "docs/../../outside/x.md", "outbox/dl"):
        r = t.run("effect", "plan", "--target", "esc", "--body", b)
        if r.rc == 0:
            c.fail("--body %s escaping the task root was accepted" % b)
    for o, n in (("docs/old.md", "../outside/a.md"), ("../outside/a.md", "docs/new.md"), ("docs/lna.md", "docs/new.md"), ("docs/dl/a.md", "docs/new.md"),
                 (os.path.join(out, "a.md"), "docs/new.md"), ("docs/old.md", "docs/dl/a.md"), ("docs/../outbox/x", "docs/new.md")):
        r = t.run("supersede", o, n)
        if r.rc == 0:
            c.fail("supersede %s %s accepted" % (o, n))
    if not os.path.exists(os.path.join(out, "a.md")):
        c.fail("supersede moved a file out of the outside dir")
    snap = snapdir(out)
    # capture: input may be anywhere
    if t.run("capture", "--from", "s", "--title", "ext", "/etc/hosts").rc:
        c.fail("capture of an outside file should be allowed")
    t.run("capture", "--from", "../..", "--title", "../../../evil", "--ref", "../x", stdin=b"x\n")
    if [x for x in os.listdir(c.base) if "evil" in x] or [x for x in os.listdir(t.dir) if "evil" in x]:
        c.fail("capture --title wrote outside context/")
    # symlinked _superseded and context
    os.makedirs(t.p("docs"), exist_ok=True)
    os.symlink(out, t.p("docs", "_superseded"))
    t.run("supersede", "docs/old.md", "docs/new.md")
    os.unlink(t.p("docs", "_superseded"))
    shutil.rmtree(t.p("context"))
    os.symlink(out, t.p("context"))
    t.run("capture", "--from", "s", "--title", "through link", stdin=b"payload through symlinked context\n")
    now = snapdir(out)
    new = sorted(set(now) - set(snap))
    if new:
        c.fail("writes landed OUTSIDE the task root via a symlinked docs/_superseded or context/: %s" % [os.path.relpath(x, c.base) for x in new])


# ---------------------------------------------------------------- save
@attack("save")
def a_save(c):
    par = c.path("par")
    os.makedirs(par)
    c.git(par, "init", "-q")
    t = Task(c, "par/task")
    r = t.run("save", "m")
    if r.rc != 1 or "git init" not in r.err:
        c.fail("save inside another repo: want exit 1 + git init fix, got %d %r" % (r.rc, r.err[:80]))
    if c.git(par, "rev-parse", "--verify", "-q", "HEAD").rc == 0 or c.git(par, "diff", "--cached", "--name-only").outb.strip():
        c.fail("save touched the parent repo")
    # no git
    t2 = Task(c, "plain")
    r = t2.run("save", "m")
    if r.rc != 1 or "error:" not in r.err:
        c.fail("save without a repo: rc=%d %r" % (r.rc, r.err[:80]))
    # real repo
    t3 = Task(c, "repo")
    c.git(t3.dir, "init", "-q")
    w = lambda p, s: (os.makedirs(os.path.dirname(t3.p(p)), exist_ok=True), open(t3.p(p), "wb").write(s))
    w("misc/ok.txt", b"fine\n")
    w("misc/aws.txt", ("key=" + SEC["aws"] + "\n").encode())
    w("misc/gh.env", ("T=" + SEC["gh"] + "\n").encode())
    w("misc/we ird\nname.txt", ("x " + SEC["sk"] + "\n").encode())
    w("misc/-dash.txt", ("x " + SEC["pk"] + "\n").encode())
    w("misc/big.txt", b"y" * 1_500_000 + SEC["slack"].encode())
    w("misc/manual.txt", SEC["jwt"].encode())
    w("scratch/s.txt", SEC["aws"].encode())
    c.git(t3.dir, "add", "misc/manual.txt")
    os.makedirs(t3.p("misc", "sub[1]"))
    os.makedirs(t3.p("misc", "nested", "deep"))
    for d in ("misc/sub[1]", "misc/nested/deep"):
        c.git(t3.p(d), "init", "-q")
        open(t3.p(d, "f.txt"), "w").write("nested content\n")
        c.git(t3.p(d), "add", "f.txt")
        c.git(t3.p(d), "commit", "-q", "-m", "n")
    t3.run("note", "n")
    r = t3.run("save", "first")
    if r.rc != 0:
        c.fail("save rc=%d %s" % (r.rc, r.err[:150]))
    files = c.git(t3.dir, "ls-tree", "-r", "--name-only", "HEAD").out
    full = c.git(t3.dir, "log", "-p", "--all", "--format=%B").out + files
    for k, v in SEC.items():
        if v in full:
            c.fail("save committed a file containing a secret (%s)" % k)
    for must in ("misc/ok.txt", ".awt/events.jsonl", "AGENTS.md"):
        if must not in files:
            c.fail("save did not commit %s" % must)
    if "scratch" in files:
        c.fail("scratch/ committed")
    if "nested" in c.git(t3.dir, "ls-tree", "-r", "HEAD").out.replace("misc/nested", "").replace("name", "") and False:
        pass
    ls = c.git(t3.dir, "ls-tree", "-r", "HEAD").out
    if "f.txt" in ls or "160000" in ls:
        c.fail("nested git repos leaked into the commit (files or gitlink): %s" % [x for x in ls.splitlines() if "sub" in x or "nested" in x or "160000" in x][:3])
    if "nested" not in r.err:
        c.fail("nested repos not reported")
    w("misc/ok.txt", b"fine\n" + SEC["gh"].encode())
    t3.run("save", "second")
    if SEC["gh"] in c.git(t3.dir, "show", "HEAD:misc/ok.txt").out:
        c.fail("secret added to tracked file got committed")
    r = t3.run("save", "third")
    for msg in ("", "-m", "--amend", "x" * 100000, "a\nb", "日本語 😀"):
        t3.run("note", "n2 " + str(len(msg)))
        t3.run("save", msg)
    t3.run("save", "last")
    full = c.git(t3.dir, "log", "-p", "--all", "--format=%B").out
    for k, v in SEC.items():
        if v in full:
            c.fail("secret in history after message fuzz (%s)" % k)
    r = c.raw([t3.awt, "save", "noid"], cwd=t3.dir, args=["save", "noid"], env=c.env(GIT_AUTHOR_NAME=None, GIT_AUTHOR_EMAIL=None, GIT_COMMITTER_NAME=None, GIT_COMMITTER_EMAIL=None, HOME=c.path("emptyhome")))


# ---------------------------------------------------------------- secrets / promises
@attack("secrets-and-caps")
def a_secrets(c):
    t = Task(c)
    for k, v in SEC.items():
        for a in (["note", "x " + v], ["ask", v], ["decide", "c", "--why", v], ["decide", "c", "--why", "w", "--tag", v], ["state", "--now", v, "--next", "n"],
                  ["state", "--now", "n", "--next", "n", "--scope", v], ["ref", "http://x/" + v, "--title", "t"], ["ref", "http://x", "--title", v, "--why", v],
                  ["effect", "plan", "--target", v, "--run", "true"], ["effect", "plan", "--target", "t", "--run", v], ["effect", "plan", "--target", "t", "--run", "true", "--verify", v],
                  ["--by", v, "note", "hello"], ["capture", "--from", v, "--title", "t"], ["capture", "--from", "s", "--title", v]):
            r = t.run(*a, stdin=b"body\n", env=c.env(AWT_BY=v) if a[0] == "effect" else None)
            if r.rc == 0:
                c.fail("secret (%s) accepted via: awt %s" % (k, " ".join(q(x) for x in a[:3])))
            if v in r.out or v in r.err:
                c.fail("secret echoed in output of: awt %s" % " ".join(q(x) for x in a[:3]))
        r = t.run("note", "hi", env=c.env(AWT_BY=v))
        if r.rc == 0:
            c.fail("secret accepted through AWT_BY (%s)" % k)
    r = t.run("note", "key=" + SEC["sk"])
    if r.rc == 0:
        c.fail("sk- secret after a non-alphanumeric character was accepted")
    r = t.run("note", "disk-encryption-rollout-plan-for-prod")
    if r.rc != 0:
        c.fail("ordinary hyphenated words were refused as a secret: " + r.err[:200])
    audit(c, t)
    # caps
    for field, a, cap in (("note", ["note", "{}"], 280), ("ask", ["ask", "{}"], 400), ("goal", ["init", "--goal", "{}", "--done", "d"], 250), ("title", ["ref", "http://c", "--title", "{}"], 120),
                          ("why", ["decide", "c", "--why", "{}"], 300), ("scope", ["state", "--now", "a", "--next", "b", "--scope", "{}"], 40), ("now", ["state", "--now", "{}", "--next", "b", "--scope", "cap"], 700),
                          ("target", ["ref", "{}", "--title", "t", "--kind", "link"], 1000)):
        n0 = rd(t).count(b"\n")
        ok = t.run(*[x.replace("{}", "漢" * cap) for x in a])
        if ok.rc:
            c.fail("%s at exactly the cap (%d chars) refused: %s" % (field, cap, ok.err.strip()[:100]))
        n1 = rd(t).count(b"\n")
        bad = t.run(*[x.replace("{}", "漢" * (cap + 1)) for x in a])
        if bad.rc != 1 or rd(t).count(b"\n") != n1 or "docs/" not in bad.err:
            c.fail("%s over cap: rc=%d wrote=%s fix mentions docs/=%s" % (field, bad.rc, rd(t).count(b"\n") != n1, "docs/" in bad.err))
    for a in (["note", " \t\n"], ["note", ""], ["ask", "  "]):
        if t.run(*a).rc != 1:
            c.fail("blank text accepted: %r" % a)
    if not (t.run("state", "--now", "same", "--next", "same").rc == 0 and t.run("state", "--now", "same", "--next", "same").rc == 1):
        c.fail("identical state not refused")
    if t.run("decide", "x", "--why", "y", "--supersedes", "d-00000000").rc != 4:
        c.fail("decide --supersedes unknown id: exit code should be 4 (id not found; help agents says so), got %d" % t.run("decide", "x", "--why", "y", "--supersedes", "d-00000000").rc)
    d1 = t.id("decide", "one", "--why", "w")
    d2 = t.id("decide", "two", "--why", "w", "--supersedes", d1)
    r = t.run("decide", "three", "--why", "w", "--supersedes", d1)
    if r.rc != 1 or d2 not in r.err:
        c.fail("superseding an already-superseded decision: want refusal naming %s" % d2)
    q1 = t.id("ask", "why?")
    if t.run("status", "done").rc != 1:
        c.fail("status done accepted with an open question")
    if t.run("answer", "q-00000000", "x").rc != 4:
        c.fail("answer unknown id: exit 4")
    t.run("answer", q1, "because")
    if t.run("answer", q1, "again").rc != 1:
        c.fail("double answer accepted")
    for tgt, kind in (("https://x.slack.com/archives/C1/p1", "slack"), ("https://a.atlassian.net/wiki/x", "confluence"), ("https://a.atlassian.net/browse/T-1", "jira"), ("ABC-123", "jira"),
                      ("https://github.com/o/r/pull/3", "pr"), ("https://example.com", "link"), ("some words", "other"), (t.dir, "repo")):
        os.makedirs(os.path.join(t.dir, ".git"), exist_ok=True) if kind == "repo" else None
        r = t.run("ref", tgt, "--title", "k")
        if "ref %s" % kind not in r.out:
            c.fail("ref %s inferred as %r, want %s" % (tgt, r.out.strip()[:30], kind))
    shutil.rmtree(t.p(".git"))
    # capture
    r = t.run("capture", "--from", "slack", "--title", "My Title!! ünï " + "x" * 80, stdin=("hello " + SEC["aws"] + " and " + SEC["gh"] + "\n").encode())
    m = re.match(r"(context/\d{8}-[a-z0-9-]{1,50}\.md) captured \(2 secrets redacted\)", r.out)
    if not m:
        c.fail("capture output: %r" % r.out[:120])
    else:
        body = open(t.p(m.group(1)), "rb").read().decode()
        if SEC["aws"] in body or "[REDACTED:" not in body or not body.startswith("---\nsource: slack\ntitle:"):
            c.fail("capture file wrong: %r" % body[:120])
        r2 = t.run("capture", "--from", "slack", "--title", "other title", stdin=("hello " + SEC["aws"] + " and " + SEC["gh"] + "\n").encode())
        if m.group(1) not in r2.out or r2.rc:
            c.fail("same-body capture not deduplicated: %r" % r2.out)
    if t.run("capture", "--from", "s", "--title", "t", stdin=b" \n").rc != 1:
        c.fail("empty capture accepted")
    a1, a2 = (t.run("capture", "--from", "s", "--title", "same slug", stdin=("body%d" % i).encode()).out for i in (1, 2))
    if a1.split()[0] == a2.split()[0]:
        c.fail("capture collision overwritten")
    # find
    for i in range(60):
        open(t.p("misc", "h%d.txt" % i), "w").write("needle line\n")
    open(t.p("scratch", "n.txt"), "w").write("needle\n")
    open(t.p("misc", "bin.dat"), "wb").write(b"needle\0")
    open(t.p("misc", "huge.txt"), "w").write("needle " * 400000)
    os.symlink(t.p("misc", "h1.txt"), t.p("misc", "lnk.txt"))
    o = t.run("find", "NEEDLE")
    L = o.out.splitlines()
    if o.rc or not L or not L[-1].startswith("+") or len(L) != 41 or any(x for x in L if "scratch" in x or "bin.dat" in x or "huge" in x or "lnk" in x or x.startswith("awt:")):
        c.fail("find caps/exclusions wrong: %d lines, last %r" % (len(L), L[-1:] ))
    if t.run("find", "zzzz-no-hit").rc != 0:
        c.fail("find with no hits not exit 0")
    # init idempotence
    d2 = Task(c, "idem", init=False)
    open(d2.p("AGENTS.md"), "w").write("mine\n")
    os.makedirs(d2.p(".claude"))
    open(d2.p(".claude", "settings.json"), "w").write("{}")
    d2.run("init", "--goal", "g", "--done", "d")

    def tree():
        return {os.path.relpath(os.path.join(a, f), d2.dir): open(os.path.join(a, f), "rb").read() for a, _, fs in os.walk(d2.dir) for f in fs if f != "awt"}
    s1 = tree()
    d2.run("init", "--goal", "g", "--done", "d")
    d2.run("init")
    s2 = tree()
    if s1 != s2:
        c.fail("init not idempotent: %s" % [k for k in set(s1) | set(s2) if s1.get(k) != s2.get(k)])
    if s1["AGENTS.md"].count(b"awt:begin") != 1 or not s1["AGENTS.md"].startswith(b"mine\n") or s1[".claude/settings.json"] != b"{}":
        c.fail("init mangled existing AGENTS.md / settings.json")
    if len(s1["AGENTS.md"]) > 2048 + 5:
        c.fail("AGENTS block over 2 KB")
    d2.run("init", "--goal", "g2", "--done", "d")
    if s1["README.md"] != tree()["README.md"]:
        c.fail("README overwritten")
    audit(c, t)


# ---------------------------------------------------------------- brief fill
@attack("brief-max-fill")
def a_brief(c):
    t = Task(c)
    wide = "漢" if c.rng.random() < .5 else "😀"
    t.run("init", "--goal", wide * 250, "--done", "字" * 250)
    repo = c.path("repo")
    c.git(c.base, "init", "-q", repo)
    for i in range(6):
        c.git(repo, "commit", "-q", "--allow-empty", "-m", "subject %d %s" % (i, "s" * 150))
    t.run("ref", repo, "--title", "r")
    for i in range(45):
        t.run("state", "--now", wide * 700 if i == 0 else "n%d" % i, "--next", "x" * 300, "--scope", "scope%02d" % i + "s" * 30)
    for i in range(30):
        t.run("ask", "q%d %s" % (i, "?" * 395))
        t.run("decide", "d%d %s" % (i, "c" * 290), "--why", "w", "--tag", "rule")
        t.run("ref", "http://x/%d" % i, "--title", "t", *(["--no-access"] if i % 2 else []))
    for i in range(25):
        open(t.p("outbox", "o%d.md" % i), "w").write("o\n")
        t.plan("tg%d%s" % (i, "t" * 190), body="outbox/o%d.md" % i)
    for i in range(30):
        d = t.p("docs", "d" * 100)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "f%d_%s.md" % (i, "n" * 120)), "w").write("x")
    for _ in range(3):
        t.append(b"junk\n" * 20000)
    b = t.run("resume")
    n = len(b.out)
    if n > 4400:
        c.fail("brief is %d chars at max fill" % n)
    if "+" not in b.out or "more: ./awt list" not in b.out:
        c.fail("no '+N more' truncation marker at max fill")
    order = [b.out.find(h) for h in ("# awt task", "## State", "## Open questions", "## Effects needing attention", "## Changes", "## Decisions", "## More")]
    if order != sorted(order) or -1 in order:
        c.fail("brief sections missing/out of order: %s" % order)
    t2 = Task(c, "t2")
    for i in range(80):
        t2.run("ask", "q%d %s" % (i, "?" * 395))
    o2 = t2.run("resume").out
    if "No handoff yet" not in o2 or len(o2) > 4400:
        c.fail("no-state brief: len=%d, handoff line present=%s" % (len(o2), "No handoff yet" in o2))


# ---------------------------------------------------------------- parallel
@attack("parallel-16-writers", solo=True)
def a_par(c):
    t = Task(c)
    secs = 4 if c.quick else 15
    acked, lk, stop = [], threading.Lock(), threading.Event()
    caps = []

    def w(k):
        i = 0
        r = random.Random(k)
        while not stop.is_set():
            i += 1
            v = r.randrange(6)
            tag = "w%d-%d-" % (k, i) + "é😀"
            if v == 0: x = t.run("note", tag)
            elif v == 1: x = t.run("ask", tag)
            elif v == 2: x = t.run("decide", tag, "--why", "w")
            elif v == 3: x = t.run("state", "--now", tag, "--next", "n", "--scope", "s%d-%d" % (k, i))
            elif v == 4: x = t.run("effect", "plan", "--target", tag, "--run", "true")
            else:
                x = t.run("capture", "--from", "p", "--title", tag, stdin=(tag + " body\n").encode())
                if x.rc == 0 and "captured" in x.out:
                    with lk:
                        caps.append(x.out.split()[0])
            if x.rc == 0:
                m = IDRX.search(x.out)
                with lk:
                    acked.append((v, m.group(0) if m else tag))
            else:
                c.fail("parallel writer got rc=%d: %s" % (x.rc, x.err.strip()[:120]))
    th = [threading.Thread(target=w, args=(k,)) for k in range(16)]
    [x.start() for x in th]
    end = time.time() + secs
    while time.time() < end:
        for a in (["resume"], ["list", "notes"], ["find", "w1-"], ["doctor"]):
            r = t.run(*a)
            if r.rc and a[0] != "doctor":
                c.fail("reader %s failed during writes: %s" % (a[0], r.err[:100]))
    stop.set()
    [x.join() for x in th]
    raw = rd(t)
    rows = [json.loads(l) for l in raw.split(b"\n") if l]
    present = {r.get("id") for r in rows} | {r.get("now") for r in rows if r["type"] == "state"}
    miss = [a for a in acked if a[1] not in present and not any(a[1] in (r.get("now"), r.get("title")) for r in rows)]
    if miss:
        c.fail("%d of %d acknowledged writes missing" % (len(miss), len(acked)))
    ids = [a[1] for a in acked if IDRX.fullmatch(a[1])]
    if len(ids) != len(set(ids)):
        c.fail("duplicate ids among acknowledged writes")
    for p in caps:
        if not os.path.exists(t.p(p)):
            c.fail("captured file missing: %s" % p)
    if len(rows) < len(acked):
        c.fail("fewer rows (%d) than acknowledged writes (%d)" % (len(rows), len(acked)))
    audit(c, t)
    t.sane("after parallel")
    if t.run("doctor").out.count("quarantined") and re.search(r"[1-9]\d* quarantined", t.run("doctor").out):
        c.fail("parallel writers produced quarantined rows")


# ---------------------------------------------------------------- node tree
def tw(c, node, *args, env=None, cwd=None, allow=(0, 1, 2, 3, 4)):
    return c.raw([sys.executable, "-I", AWT, "--dir", node] + list(args), cwd=cwd or c.base, env=env, args=list(args), allow=allow)


def tree_root(c):
    top = c.path("tree")
    os.makedirs(top)
    r = tw(c, top, "init", "--kind", "root")
    if r.rc != 0:
        c.fail("cannot make a root: " + r.err[:120])
    return top


def tree_nodes(base):
    """Walk only the reserved child directories, the way awt defines a tree. Returns (nodes, leftovers)."""
    nodes, left = [], []
    for plural in ("workspaces", "tasks", "agents"):
        d = os.path.join(base, plural)
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            p = os.path.join(d, n)
            (left if n.startswith(".new-") else nodes).append(p)
    return nodes, left


def first_row(node):
    try:
        with open(os.path.join(node, ".awt", "events.jsonl"), "rb") as g:
            ln = g.readline()
        return json.loads(ln.decode("utf-8"))
    except Exception:
        return None


def tree_audit(c, base):
    """I2 and I4 below base: every visible node is complete, keys are unique among siblings."""
    nodes, _ = tree_nodes(base)
    keys = {}
    for n in nodes:
        r = first_row(n)
        if not r or r.get("type") != "node":
            c.fail("visible node without a complete node row: " + n)
            continue
        k = r.get("key")
        if k:
            if (os.path.dirname(n), k) in keys:
                c.fail("duplicate key %r under %s" % (k, os.path.dirname(n)))
            keys[(os.path.dirname(n), k)] = n
        tree_audit(c, n)


@attack("tree-race-key")
def a_tree_race_key(c):
    top = tree_root(c)
    ws = tw(c, top, "init", "--kind", "workspace", "--name", "w").out.split()[1]
    w = os.path.join(top, ws)
    n = 12 if c.quick else 32
    with cf.ThreadPoolExecutor(n) as ex:
        rs = list(ex.map(lambda i: tw(c, w, "init", "--kind", "task", "--name", "t%d" % (i % 3), "--key", "K", "--goal", "g", "--done", "d"), range(n)))
    if any(r.rc != 0 for r in rs):
        c.fail("a keyed creator failed: " + next(r.err for r in rs if r.rc != 0)[:120])
    if len({r.out.strip() for r in rs}) != 1:
        c.fail("creators disagree on the path: %s" % sorted({r.out.strip() for r in rs})[:3])
    nodes, _ = tree_nodes(w)
    if len(nodes) != 1:
        c.fail("expected one node for one key, found %d" % len(nodes))
    tree_audit(c, top)


@attack("tree-race-names")
def a_tree_race_names(c):
    top = tree_root(c)
    w = os.path.join(top, tw(c, top, "init", "--kind", "workspace", "--name", "w").out.split()[1])
    n = 12 if c.quick else 32
    with cf.ThreadPoolExecutor(n) as ex:
        rs = list(ex.map(lambda i: tw(c, w, "init", "--kind", "task", "--name", "same", "--key", "k%d" % i, "--goal", "g", "--done", "d"), range(n)))
    if any(r.rc != 0 for r in rs):
        c.fail("a creator failed: " + next(r.err for r in rs if r.rc != 0)[:120])
    nodes, _ = tree_nodes(w)
    if len(nodes) != n or len({r.out.strip() for r in rs}) != n:
        c.fail("expected %d distinct nodes, found %d dirs and %d distinct paths" % (n, len(nodes), len({r.out.strip() for r in rs})))
    tree_audit(c, top)


@attack("tree-kill-init")
def a_tree_kill_init(c):
    top = tree_root(c)
    w = os.path.join(top, tw(c, top, "init", "--kind", "workspace", "--name", "w").out.split()[1])
    t = os.path.join(w, tw(c, w, "init", "--kind", "task", "--name", "t", "--goal", "g", "--done", "d").out.split()[1])
    rounds = 40 if c.quick else 200
    for i in range(rounds):
        cmd = [sys.executable, "-I", AWT, "--dir", t, "init", "--kind", "agent", "--name", "a", "--key", "k%d" % (i % 10)]
        c.log(" ".join(cmd))
        p = subprocess.Popen(cmd, env=c.env(), cwd=c.base, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(c.rng.random() * 0.04)
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        p.wait()
    tree_audit(c, top)
    for i in range(10):
        r = tw(c, t, "init", "--kind", "agent", "--name", "a", "--key", "k%d" % i)
        if r.rc != 0:
            c.fail("retry after kill failed: " + r.err[:120])
    agents = [n for n in tree_nodes(t)[0]]
    ks = sorted(first_row(n)["key"] for n in agents)
    if ks != sorted("k%d" % i for i in range(10)):
        c.fail("after retries expected exactly keys k0..k9, found %s" % ks)
    d = tw(c, t, "doctor")
    if d.rc not in (0, 1):
        c.fail("doctor crashed")


@attack("tree-hostile-names")
def a_tree_hostile_names(c):
    top = tree_root(c)
    w = os.path.join(top, tw(c, top, "init", "--kind", "workspace", "--name", "w").out.split()[1])
    alphabet = ["a", "Z", "9", " ", "-", "_", ".", "/", "\\", "..", "é", "😀", "\n", "\t", "\x1b", "\u202e", "$", "`", "'", '"', "*", "~", ":"]
    for i in range(60 if c.quick else 400):
        name = "".join(c.rng.choice(alphabet) for _ in range(c.rng.randrange(1, 70)))
        tw(c, w, "init", "--kind", "task", "--name", name, "--goal", "g", "--done", "d")
    nodes, left = tree_nodes(w)
    for n in nodes:
        if not re.fullmatch(r"[a-z0-9-]{1,50}", os.path.basename(n)):
            c.fail("bad directory name %r" % os.path.basename(n))
    if left:
        c.fail("leftover .new dirs after clean runs: %d" % len(left))
    extra = set(os.listdir(w)) - {"tasks", "context", "docs", "misc", ".awt", ".gitignore"}
    if extra:
        c.fail("something escaped into the workspace dir: %s" % sorted(extra)[:5])
    tree_audit(c, top)


def tnode(c, parent, kind, name, *extra, key=None):
    a = ["init", "--kind", kind, "--name", name] + (["--key", key] if key else []) + list(extra)
    if kind == "task":
        a += ["--goal", "goal of " + name, "--done", "done"]
    r = tw(c, parent, *a)
    if r.rc != 0:
        c.fail("could not make %s %s: %s" % (kind, name, r.err[:100]))
        return None
    return os.path.join(parent, r.out.split()[1])


def readers(c, node):
    """Every read verb on node must succeed and print valid JSON where promised."""
    for args in (["resume"], ["list", "tree"], ["list", "nodes"], ["find", "--tree", "goal"], ["list", "refs"]):
        r = tw(c, node, *args)
        if r.rc != 0:
            c.fail("read failed rc=%d: awt %s -> %s" % (r.rc, " ".join(args), r.err.strip()[:100]))
    for args in (["list", "nodes", "--json"], ["resume", "--json"]):
        r = tw(c, node, *args)
        try:
            json.loads(r.out)
        except ValueError:
            c.fail("invalid JSON from awt %s: %s" % (" ".join(args), r.err.strip()[:100] or r.out[:80]))
    r = tw(c, node, "doctor")
    if r.rc not in (0, 1):
        c.fail("doctor rc=%d" % r.rc)


@attack("tree-mutate-while-reading")
def a_tree_mutate(c):
    top = tree_root(c)
    w = tnode(c, top, "workspace", "w")
    t = tnode(c, w, "task", "t")
    stop, errs = threading.Event(), []

    def mutator(k):
        i = 0
        while not stop.is_set():
            i += 1
            a = tnode(c, t, "agent", "m%d-%d" % (k, i), key="k%d-%d" % (k, i))
            if a and i % 3 == 0:
                shutil.rmtree(a, ignore_errors=True)
            elif a and i % 5 == 0:
                dest = c.path("moved-%d-%d" % (k, i))
                try:
                    shutil.move(a, dest)
                except OSError:
                    pass
    th = [threading.Thread(target=mutator, args=(k,)) for k in range(4)]
    [x.start() for x in th]
    end = time.time() + (4 if c.quick else 15)
    while time.time() < end:
        for args in (["resume"], ["list", "tree"], ["list", "nodes", "--json"], ["find", "--tree", "goal"], ["doctor"]):
            r = tw(c, t, *args)
            if r.rc != 0 and args[0] != "doctor":
                c.fail("reader failed during mutation: awt %s -> %s" % (" ".join(args), r.err.strip()[:100]))
            if args[-1] == "--json":
                try:
                    json.loads(r.out)
                except ValueError:
                    c.fail("invalid JSON during mutation")
    stop.set()
    [x.join() for x in th]
    tree_audit(c, top)


@attack("tree-hostile-layout")
def a_tree_hostile_layout(c):
    top = tree_root(c)
    w = tnode(c, top, "workspace", "w")
    t = tnode(c, w, "task", "t")
    deep = t
    for i in range(10):
        deep = tnode(c, deep, "task", "d%d" % i) or deep
    os.symlink(top, os.path.join(t, "agents-loop"))
    os.makedirs(os.path.join(t, "agents"), exist_ok=True)
    os.symlink(top, os.path.join(t, "agents", "up"))
    os.symlink("/", os.path.join(t, "agents", "rootlink"))
    os.makedirs(os.path.join(t, "agents", "no-awt-dir"))
    legacy = os.path.join(t, "agents", "legacy")
    os.makedirs(os.path.join(legacy, ".awt"))
    with open(os.path.join(legacy, ".awt", "events.jsonl"), "w") as g:
        g.write("")
    bad = os.path.join(t, "agents", "corrupt")
    os.makedirs(os.path.join(bad, ".awt"))
    with open(os.path.join(bad, ".awt", "events.jsonl"), "wb") as g:
        g.write(b"{not json\n\xff\xfe\n")
    for n in ("Case", "case", "CASE"):
        tnode(c, t, "agent", n)
    os.makedirs(os.path.join(w, "tasks", "file-not-dir"), exist_ok=True)
    with open(os.path.join(w, "tasks", "plain-file"), "w") as g:
        g.write("x")
    for i in range(150 if c.quick else 400):
        tnode(c, t, "agent", "s%03d" % i)
    for node in (top, w, t, deep, legacy, bad):
        readers(c, node)
    d = tw(c, t, "doctor").out
    for needle in ("symlink", "no node row"):
        if needle not in d:
            c.fail("doctor did not report %r" % needle)


@attack("tree-status-race")
def a_tree_status_race(c):
    top = tree_root(c)
    w = tnode(c, top, "workspace", "w")
    for rnd in range(8 if c.quick else 30):
        t = tnode(c, w, "task", "t%d" % rnd)
        with cf.ThreadPoolExecutor(2) as ex:
            f1 = ex.submit(tw, c, t, "status", "done")
            f2 = ex.submit(tw, c, t, "init", "--kind", "task", "--name", "late", "--goal", "g", "--done", "d")
            r1, r2 = f1.result(), f2.result()
        kids = tree_nodes(t)[0]
        if r1.rc == 1 and not kids and r2.rc == 0:
            c.fail("done refused although no child existed afterwards")
        if r1.rc == 0 and kids:
            d = tw(c, w, "doctor").out
            if "is done but" not in d and "late" in " ".join(kids):
                c.fail("done parent with an active child was not reported by doctor")
        readers(c, t)


@attack("tree-parallel-agents")
def a_tree_parallel_agents(c):
    top = tree_root(c)
    w = tnode(c, top, "workspace", "w")
    t = tnode(c, w, "task", "t")
    n = 20 if c.quick else 50
    agents = [tnode(c, t, "agent", "a%02d" % i, key="agt_%d" % i) for i in range(n)]
    stop = threading.Event()

    def w_(i):
        j = 0
        env = c.env(AWT_BY="agt_%d" % i)
        while not stop.is_set() and agents[i]:
            j += 1
            r = c.raw([sys.executable, "-I", AWT, "--dir", agents[i], "state", "--now", "step %d of %d" % (j, i), "--next", "n"], cwd=c.base, env=env, args=["state"])
            if r.rc != 0:
                c.fail("agent write failed: " + r.err[:100])
    th = [threading.Thread(target=w_, args=(i,)) for i in range(n)]
    [x.start() for x in th]
    end = time.time() + (4 if c.quick else 12)
    while time.time() < end:
        r = tw(c, t, "resume")
        if r.rc != 0:
            c.fail("resume failed under writes")
        r = tw(c, t, "list", "nodes", "--json")
        try:
            if len(json.loads(r.out)) != n:
                c.fail("node count changed under writes")
        except ValueError:
            c.fail("invalid JSON under writes")
    stop.set()
    [x.join() for x in th]
    for i in range(n):
        rows = [json.loads(l) for l in rd_node(agents[i]) if l.strip()]
        if any(r.get("by") not in ("agt_%d" % i, "agent") for r in rows):
            c.fail("row from another agent in agt_%d's log" % i)
    tree_audit(c, top)


def rd_node(node):
    with open(os.path.join(node, ".awt", "events.jsonl"), "rb") as g:
        return g.read().decode("utf-8", "replace").splitlines()


@attack("tree-budget-fuzz")
def a_tree_budget_fuzz(c):
    top = tree_root(c)
    w = tnode(c, top, "workspace", "w")
    chars = ["a", "é", "😀", "漢", " ", "\t", "\x1b", "\u202e"]
    word = lambda n: "".join(c.rng.choice(chars) for _ in range(n))
    for i in range(10):
        tw(c, w, "decide", "rule " + word(c.rng.randrange(1, 280)), "--why", "w", "--tag", "rule")
    cur = w
    for i in range(c.rng.randrange(1, 6)):
        cur = tnode(c, cur, "task", "t%d" % i) or cur
    for i in range(c.rng.randrange(5, 60)):
        a = tnode(c, cur, "agent", "a%d" % i)
        if a:
            tw(c, a, "state", "--now", "n" + word(c.rng.randrange(1, 690)), "--next", "x" + word(c.rng.randrange(1, 290)))
    r = tw(c, cur, "resume")
    if len(r.out) > 5200:
        c.fail("brief %d > 5200" % len(r.out))
    if any(len(l) > 1300 for l in r.out.splitlines()):
        c.fail("a brief line is absurdly long")
    tree_audit(c, top)


@attack("tree-secret-hygiene")
def a_tree_secrets(c):
    top = tree_root(c)
    w = tnode(c, top, "workspace", "w")
    for k, v in SEC.items():
        for flag in ("--name", "--key"):
            a = ["init", "--kind", "task", "--goal", "g", "--done", "d", "--name", "ok", "--key", "ok"]
            a[a.index(flag) + 1] = "x " + v
            r = tw(c, w, *a)
            if r.rc == 0:
                c.fail("secret %s accepted in %s" % (k, flag))
    for dp, dns, fns in os.walk(top):
        for n in fns:
            try:
                data = open(os.path.join(dp, n), encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for rx in SECRE:
                if rx.search(data):
                    c.fail("secret-shaped text reached disk: " + os.path.join(dp, n))
    if tree_nodes(w)[0]:
        c.fail("a refused init left a node behind")


# ---------------------------------------------------------------- driver
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--only")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    seed = a.seed if a.seed is not None else random.SystemRandom().randrange(1 << 30)
    base = tempfile.mkdtemp(prefix="awtchaos-")
    if not os.path.exists(AWT):
        print("cannot find awt at", AWT)
        return 2
    sel = [x for x in ATTACKS if not a.only or a.only in x[0]]
    results, lk = {}, threading.Lock()

    def one(item):
        name, f, solo = item
        c = Ctx(name, os.path.join(base, name), seed, a.quick)
        t0 = time.time()
        try:
            f(c)
        except BaseException as x:
            import traceback
            c.fail("chaos harness error (test bug?): %s: %s" % (type(x).__name__, traceback.format_exc().strip().splitlines()[-3:]))
        dt = time.time() - t0
        with lk:
            status = "SKIP" if c.skipped else "FAIL" if c.fails else "ok  "
            print("%s %-44s %5.1fs%s" % (status, name, dt, ("  (" + c.skipped + ")") if c.skipped else ""), flush=True)
            for n in c.notes:
                print("     note: " + n)
            for m in c.fails:
                print("     - " + m)
            results[name] = c
        return c
    try:
        print("awt chaos  seed=%d  %s  awt=%s" % (seed, "quick" if a.quick else "full", AWT), flush=True)
        t0 = time.time()
        par = [x for x in sel if not x[2]]
        with cf.ThreadPoolExecutor(a.jobs) as ex:
            list(ex.map(one, par))
        for x in [x for x in sel if x[2]]:
            one(x)
        bad = [c for c in results.values() if c.fails]
        for c in bad:
            print("\nFAILED %s  (reproduce: python3 tests/chaos.py --seed %d%s --only %s)" % (c.name, seed, " --quick" if a.quick else "", c.name))
            print("  last commands (run in a scratch task made by: mkdir t && cp awt t/ && cd t && ./awt init --goal g --done d):")
            for l in c.cmds[-14:]:
                print("    " + l[:300])
        print("\n%d attacks, %d failed, %.0fs, seed=%d" % (len(results), len(bad), time.time() - t0, seed))
        return 1 if bad else 0
    finally:
        if a.keep:
            print("kept", base)
        else:
            for dp, dns, fns in os.walk(base):
                for d in dns:
                    try:
                        os.chmod(os.path.join(dp, d), 0o755)
                    except OSError:
                        pass
            shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
