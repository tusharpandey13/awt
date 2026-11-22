"""Shared fixture H2 for the two-host tests (docs/e2e-two-host-sync.md section 0): two hosts on one machine,
each with its own HOME, store and clone of one task tree, and one bare git repository as the remote.
Only temp dirs are used. No ssh, no real GitHub, no network."""
import json, os, shutil, sqlite3, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
WT = os.path.dirname(HERE)
AWT = os.path.join(WT, "awt")
SYNC = os.path.join(WT, "awt-sync")
STRIP = ("AWT_", "PASEO_", "CLAUDECODE", "GIT_", "SSH_")


def have_git():
    return shutil.which("git") is not None


def realtmp(prefix="awt-hs-"):
    return os.path.realpath(tempfile.mkdtemp(prefix=prefix))


def clean_env(T, home, **over):
    e = {k: v for k, v in os.environ.items() if not k.startswith(STRIP) and k not in ("HOME",)}
    e.update(HOME=home, TZ="UTC", GIT_CONFIG_GLOBAL=os.path.join(T, "gitconfig"), GIT_CONFIG_NOSYSTEM="1", PYTHONDONTWRITEBYTECODE="1", GIT_TERMINAL_PROMPT="0")
    for k, v in over.items():
        if v is None:
            e.pop(k, None)
        else:
            e[k] = v
    return e


def write_gitconfig(T):
    with open(os.path.join(T, "gitconfig"), "w") as g:
        g.write("[user]\n\tname = parsekit-bot\n\temail = bot@parsekit.invalid\n[init]\n\tdefaultBranch = main\n[protocol \"file\"]\n\tallow = always\n")


def run(argv, cwd=None, env=None, timeout=120, stdin=None):
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, input=stdin)


class H2:
    """T/remote.git, T/A/{home,store,tree}, T/B/{home,store,tree}. Hosts are named host-a and host-b."""

    def __init__(self, awt=AWT, sync=SYNC):
        self.awt_path, self.sync_path = awt, sync
        self.T = realtmp()
        write_gitconfig(self.T)
        self.skew = {"A": None, "B": None}
        self.remote = os.path.join(self.T, "remote.git")
        for h in "AB":
            for d in ("home", "store"):
                os.makedirs(os.path.join(self.T, h, d))
        self.git_T("init", "-q", "--bare", self.remote)

    def cleanup(self):
        shutil.rmtree(self.T, ignore_errors=True)

    def tree(self, h):
        return os.path.join(self.T, h, "tree")

    def env(self, h, **over):
        e = clean_env(self.T, os.path.join(self.T, h, "home"), AWT_STORE=os.path.join(self.T, h, "store"), AWT_HOST="host-" + h.lower(),
                      AWT_ROOT=self.tree(h), AWT_MODEL="claude-test-1")
        if self.skew[h] is not None:
            e["AWT_TEST_CLOCK_SKEW_S"] = str(self.skew[h])
        e.update({k: v for k, v in over.items() if v is not None})
        for k, v in over.items():
            if v is None:
                e.pop(k, None)
        return e

    def git_T(self, *a, **kw):
        return run(["git"] + list(a), cwd=self.T, env=clean_env(self.T, self.T), **kw)

    def git(self, h, *a, **kw):
        return run(["git", "-C", self.tree(h)] + list(a), env=self.env(h), **kw)

    def awt(self, h, *a, dir=None, awt=None, **kw):
        env = kw.pop("env", None) or self.env(h, **kw.pop("over", {}))
        cmd = [sys.executable, "-I", awt or self.awt_path] + (["--dir", dir] if dir else []) + list(a)
        return run(cmd, cwd=kw.pop("cwd", self.tree(h)), env=env, **kw)

    def sync(self, h, *a, **kw):
        env = self.env(h, **kw.pop("over", {}))
        return run([sys.executable, "-I", self.sync_path, "--dir", self.tree(h)] + list(a), env=env, **kw)

    def cutover(self):
        return [self.sync("A"), self.sync("B"), self.sync("A")]

    def node(self, h, rel):
        return os.path.join(self.tree(h), rel)

    TASK = "projects/parsekit/workspaces/main/tasks/work"
    TASK2 = "projects/ledgerline/workspaces/main/tasks/work"

    def setup(self, hook=True):
        """E-HS1 setup steps 1-5."""
        T, A, B = self.T, self.tree("A"), self.tree("B")
        os.makedirs(A)
        ok = lambda r: (r.returncode == 0) or (_ for _ in ()).throw(AssertionError("%s\n%s%s" % (r.args, r.stdout, r.stderr)))
        ok(self.awt("A", "init", "--kind", "root", "--name", "tree"))
        for p in ("parsekit", "ledgerline"):
            ok(self.awt("A", "init", "--kind", "project", "--name", p))
            ok(self.awt("A", "init", "--kind", "workspace", "--name", "main", dir=self.node("A", "projects/" + p)))
            ok(self.awt("A", "init", "--kind", "task", "--name", "work", "--goal", "Ship " + p, "--done", "Merged", dir=self.node("A", "projects/%s/workspaces/main" % p)))
        ok(self.git("A", "init", "-q"))
        with open(os.path.join(A, ".gitattributes"), "w") as g:
            g.write("events.jsonl merge=union\n")
        if hook:
            self.install_hook("A")
        ok(self.awt("A", "ref", self.remote, "--kind", "sync", "--title", "private sync remote"))
        ok(self.git("A", "remote", "add", "origin", self.remote))
        ok(self.git("A", "add", "-A"))
        ok(self.git("A", "commit", "-q", "-m", "init"))
        ok(self.git("A", "push", "-q", "origin", "HEAD:main"))
        ok(run(["git", "clone", "-q", self.remote, B], env=clean_env(T, T)))
        if hook:
            self.install_hook("B")

    def install_hook(self, h):
        p = os.path.join(self.tree(h), ".git", "hooks", "pre-commit")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as g:
            g.write("#!/bin/sh\nexec %s -I %s doctor --staged\n" % (sys.executable, self.awt_path))
        os.chmod(p, 0o755)

    def rows(self, h, rel=TASK):
        """Raw ledger lines of a node on host h."""
        with open(os.path.join(self.tree(h), rel, ".awt", "events.jsonl"), "rb") as g:
            return [x for x in g.read().split(b"\n") if x.strip()]

    SECTIONS = ("decisions", "questions", "effects", "notes", "state", "refs")

    def listing(self, h, rel=TASK):
        """`list SECTION --all --json` for every ledger section, joined."""
        return "\n".join(self.awt(h, "list", sec, "--all", "--json", dir=self.node(h, rel)).stdout for sec in self.SECTIONS)

    def all_lines(self, h):
        """{node relative path: sorted ledger lines} for every node of the tree on host h."""
        res = {}
        for dp, dns, fns in os.walk(self.tree(h)):
            dns[:] = [d for d in dns if d != ".git"]
            if os.path.basename(dp) == ".awt" and "events.jsonl" in fns:
                with open(os.path.join(dp, "events.jsonl"), "rb") as g:
                    res[os.path.relpath(os.path.dirname(dp), self.tree(h))] = sorted(x for x in g.read().split(b"\n") if x.strip())
        return res


def rsync(src_store, dst_store, stop=None):
    """Test helper for the rsync of log/: never deletes; copies a file only when the target is missing or a byte prefix of the source.
    stop = (relative path, K): copy only the first K bytes of that file. Returns the files it left alone because both copies differ (divergent)."""
    divergent = []
    for dp, dns, fns in os.walk(os.path.join(src_store, "log")):
        for f in fns:
            s = os.path.join(dp, f)
            rel = os.path.relpath(s, src_store)
            d = os.path.join(dst_store, rel)
            with open(s, "rb") as g:
                data = g.read()
            if stop and stop[0] == rel:
                data = data[:stop[1]]
            if os.path.exists(d):
                with open(d, "rb") as g:
                    cur = g.read()
                if cur == data[:len(cur)]:
                    if len(cur) == len(data):
                        continue
                elif not data.startswith(cur):
                    divergent.append(rel)
                    continue
            os.makedirs(os.path.dirname(d), exist_ok=True)
            with open(d, "wb") as g:
                g.write(data)
    return divergent


def ledger_blobs(remote, T):
    """Every .awt/events.jsonl blob in every commit of the bare remote: [(commit, path, bytes, [parent blobs])]."""
    env = clean_env(T, T)
    res = []
    revs = run(["git", "-C", remote, "rev-list", "--all"], env=env).stdout.split()
    for c in revs:
        parents = run(["git", "-C", remote, "rev-list", "--parents", "-n", "1", c], env=env).stdout.split()[1:]
        files = run(["git", "-C", remote, "ls-tree", "-r", "--name-only", c], env=env).stdout.split("\n")
        for f in files:
            if f.endswith(".awt/events.jsonl") or f == ".awt/events.jsonl":
                b = subprocess.run(["git", "-C", remote, "cat-file", "blob", "%s:%s" % (c, f)], capture_output=True, env=env).stdout
                pb = []
                for p in parents:
                    r = subprocess.run(["git", "-C", remote, "cat-file", "blob", "%s:%s" % (p, f)], capture_output=True, env=env)
                    if r.returncode == 0:
                        pb.append(r.stdout)
                res.append((c, f, b, pb))
    return res


def check_is4(remote, T):
    """IS4: every ledger blob ends with a newline; a first-parent blob is a prefix, or (a merge) the blob holds both parents' lines; fsck passes."""
    bad = []
    for c, f, b, pb in ledger_blobs(remote, T):
        if b and not b.endswith(b"\n"):
            bad.append("%s %s: no final newline" % (c[:8], f))
        if len(pb) == 1 and not b.startswith(pb[0]):
            bad.append("%s %s: parent is not a prefix" % (c[:8], f))
        if len(pb) > 1:
            lines = set(b.split(b"\n"))
            for p in pb:
                if not set(x for x in p.split(b"\n") if x.strip()) <= lines:
                    bad.append("%s %s: merge lost a parent's lines" % (c[:8], f))
    r = run(["git", "-C", remote, "fsck", "--strict"], env=clean_env(T, T))
    if r.returncode:
        bad.append("fsck: " + (r.stderr or r.stdout)[-200:])
    return bad


def logical(db_path, words=("alphaword", "betaword", "cargo", "note")):
    """store.db without rowids and without the ingest_sources snapshot (it holds the run time): every table's rows sorted, plus what a few words hit in the full-text index (IS5)."""
    c = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    try:
        res = {}
        for (t,) in c.execute("select name from sqlite_master where type='table' and name not like 'fts_text%' and name not in ('fts_ref', 'build_state', 'ingest_sources') order by name").fetchall():
            res[t] = sorted(map(repr, c.execute("select * from " + t).fetchall()))
        for w in words:
            res["fts:" + w] = sorted(c.execute("select r.kind, coalesce(m.text, t.args, x.fields) from fts_text join fts_ref r on r.id = fts_text.rowid "
                                               "left join messages m on r.kind='message' and m.rowid=r.ref left join tool_calls t on r.kind='tool_call' and t.rowid=r.ref "
                                               "left join records x on r.kind='record' and x.rowid=r.ref where fts_text match ?", ('"%s"' % w,)).fetchall())
        return res
    finally:
        c.close()


def write_session(T, host, sid, cwd, cmds, word, hours_ago=1):
    """A fictional Claude transcript for host ("A" or "B") that runs Bash tool calls; every row is dated within the last day."""
    import datetime
    proj = os.path.join(T, host, "home", ".claude", "projects", "-work-" + sid[:6])
    os.makedirs(proj, exist_ok=True)
    base = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours_ago)
    path = os.path.join(proj, sid + ".jsonl")
    with open(path, "w") as g:
        for i, c in enumerate([None] + list(cmds)):
            r = dict(type="user" if c is None else "assistant", uuid="%s-%d" % (sid[:4], i), parentUuid="%s-%d" % (sid[:4], i - 1) if i else None, sessionId=sid, cwd=cwd,
                     timestamp=(base + datetime.timedelta(seconds=5 * i)).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
            if c is None:
                r["message"] = {"role": "user", "content": "please look at %s" % word}
            else:
                r["message"] = {"role": "assistant", "model": "claude-test-1", "stop_reason": "tool_use", "usage": {"input_tokens": 5, "output_tokens": 7},
                                "content": [{"type": "text", "text": "running"}, {"type": "tool_use", "id": "t%d" % i, "name": "Bash", "input": {"command": c}}]}
            g.write(json.dumps(r) + "\n")
    return path
