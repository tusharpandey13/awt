"""Every ./awt command shown in the docs must use a real verb and real flags."""
import glob, os, re, subprocess, sys, tempfile, shutil, unittest

# Hermetic: an agent running the tests has AWT_DIR pointing at its own node; the tests must never act on it.
for _k in ("AWT_DIR", "AWT_BY"):
    os.environ.pop(_k, None)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AWT = os.path.join(REPO, "awt")


def run(*a):
    return subprocess.run([sys.executable, AWT] + list(a), capture_output=True, text=True, timeout=30)


def docs():
    for name in ["README.md", "AGENTS.md"] + sorted(glob.glob(os.path.join(REPO, "docs", "*.md"))):
        path = name if os.path.isabs(name) else os.path.join(REPO, name)
        if os.path.basename(path) == "example-session.md":  # a recording, including an agent's own wrong guess
            continue
        with open(path, encoding="utf-8") as f:
            yield os.path.relpath(path, REPO), f.read()
    yield "help agents", run("help", "agents").stdout
    d = tempfile.mkdtemp()
    try:
        shutil.copy2(AWT, d)
        subprocess.run(["./awt", "init"], cwd=d, capture_output=True)
        with open(os.path.join(d, "AGENTS.md"), encoding="utf-8") as f:
            yield "AGENTS.md block", f.read()
    finally:
        shutil.rmtree(d, ignore_errors=True)
    d = tempfile.mkdtemp()
    try:
        subprocess.run([sys.executable, AWT, "--dir", d, "init", "--kind", "root"], capture_output=True)
        with open(os.path.join(d, "AGENTS.md"), encoding="utf-8") as f:
            yield "tree AGENTS.md block", f.read()
        with open(os.path.join(d, "README.md"), encoding="utf-8") as f:
            yield "tree README.md", f.read()
    finally:
        shutil.rmtree(d, ignore_errors=True)


def flags_for(words):
    return run(*(words + ["--help"]))


class Docs(unittest.TestCase):
    def test_commands_exist(self):
        bad, seen = [], 0
        for src, text in docs():
            for m in re.finditer(r"(?:\./)?\bawt ([a-z]+)((?: [a-z]+)?)([^\n`|]*)", text):
                verb, sub, rest = m.group(1), m.group(2).strip(), m.group(3)
                if verb in ("guide", "agent", "task", "is", "stays", "marked", "chaos", "repo", "and", "or", "the", "on", "to", "in", "work", "turns", "does", "can", "with"):
                    continue
                words = [verb] + ([sub] if verb == "effect" and sub else [])
                if verb in ("help",):
                    continue
                h = flags_for(words)
                seen += 1
                if h.returncode != 0:
                    bad.append("%s: awt %s" % (src, " ".join(words)))
                    continue
                for fl in re.findall(r"(?:^|\s)(--[a-z-]+)", rest):
                    if fl not in h.stdout and fl != "--help":
                        bad.append("%s: awt %s has no %s" % (src, " ".join(words), fl))
        self.assertGreater(seen, 30)
        self.assertEqual(sorted(set(bad)), [])

    def test_tree_block_was_derived_cleanly(self):
        blocks = dict(docs())
        tree, plain = blocks["tree AGENTS.md block"], blocks["AGENTS.md block"]
        self.assertIn("./awt", plain)
        for stale in ("./awt", "Everything about this task lives here", "docs/<brief>.out.md"):
            self.assertNotIn(stale, tree)
        for fresh in ("$AWT_DIR/out.md", "$AWT_DIR/BRIEF.md"):
            self.assertIn(fresh, tree)

    def test_tree_block_opens_with_the_node_rule_and_fits_2kb(self):
        tree = dict(docs())["tree AGENTS.md block"]
        self.assertIn("\nYour node is `$AWT_DIR` if set, else this directory. Never hand-edit `.awt/`", tree)
        self.assertLessEqual(len(tree.encode()), 2048)

    def test_no_real_paths_or_hosts_in_docs(self):
        for src, text in docs():
            self.assertNotRegex(text, r"/Users/[a-z]+/")


# ---- help, man page and reference agree (ARCHITECTURE-v2 phase 6) ----
sys.path.insert(0, os.path.join(REPO, "tools"))
import gen_docs  # noqa: E402

M = gen_docs.load_awt()
ENTRIES = gen_docs.entries(M)  # [(key, parser)]
GLOBALS = ["--dir", "--by", "--model", "--version"]
# flags in README/AGENTS that belong to other tools or to scripts beside awt
FOREIGN = {"--ref", "--dry-run", "--home", "--ignore-missing", "--hooks", "--version", "-p"}


def norm(t):
    return " ".join(t.split())


def flags_of(q):
    return sorted(o for a in q._actions for o in a.option_strings if o.startswith("--") and o != "--help" and a.help != "==SUPPRESS==")


def read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


def man_sections():
    out, cur = {}, None
    for line in read("docs/awt.1").splitlines():
        if line.startswith(".SS "):
            cur = line[4:].replace("\\-", "-")
            out[cur] = []
        elif line.startswith(".SH "):
            cur = None
        elif cur:
            out[cur].append(line.replace("\\-", "-"))
    return {k: "\n".join(v) for k, v in out.items()}


def md_flags(text):
    return sorted(set(re.findall(r"^\| `(--[a-z-]+)", text, re.M)))


class HelpManReference(unittest.TestCase):
    def test_root_help_man_and_reference_list_the_same_verbs(self):
        keys = sorted(k for k, _ in ENTRIES)
        verbs = sorted(k for k in keys if " " not in k)
        helptext = run("--help").stdout
        self.assertEqual(sorted(re.findall(r"^  ([a-z]+) {2,}\S", helptext.split("\nglobal:")[0], re.M)), verbs)
        for g in GLOBALS:
            self.assertIn(g, helptext)
            self.assertIn(g, read("docs/awt.1").replace("\\-", "-"))
        self.assertEqual(sorted(man_sections()), keys)
        pages = sorted(f[:-3] for f in os.listdir(os.path.join(REPO, "docs", "reference")) if f.endswith(".md"))
        self.assertEqual(pages, sorted([gen_docs.slug(k) for k in keys] + ["index"]))
        index = read("docs/reference/index.md")
        for v in verbs:
            self.assertIn("[`%s`](%s.md)" % (v, v), index)

    def test_every_flag_and_argument_is_in_help_man_and_reference(self):
        man = man_sections()
        for key, q in ENTRIES:
            words = key.split()
            h = norm(run(*(words + ["--help"])).stdout)
            self.assertEqual(run(*(words + ["--help"])).returncode, 0, key)
            ref = read("docs/reference/%s.md" % gen_docs.slug(key))
            truth = flags_of(q)
            self.assertEqual(md_flags(ref), truth, "reference flags: " + key)
            self.assertEqual(sorted(set(re.findall(r"^\.B (--[a-z-]+)", man[key], re.M))), truth, "man flags: " + key)
            for f in truth:
                self.assertIn(f, h, "help: %s %s" % (key, f))
            pos, opt = gen_docs.args_of(q)
            summary = M.CLI_HELP[key][0]
            for where, text in (("help", h), ("man", norm(man[key])), ("reference", norm(ref))):
                self.assertIn(norm(summary), text, "%s: summary of %s" % (where, key))
                for _, _, doc, _ in pos + opt:
                    want = norm(doc)
                    self.assertIn(want, text, "%s: %s: %r" % (where, key, doc))

    def test_every_documented_argument_has_help_text(self):
        for key, q in ENTRIES:
            for a in q._actions:
                if a.dest not in ("help", "eop") and a.help != "==SUPPRESS==":
                    self.assertTrue(a.help, "%s %s has no help text" % (key, a.dest))

    def test_generated_files_are_current(self):
        for rel, text in gen_docs.render(M).items():
            self.assertEqual(read(rel), text, "%s is stale: run python3 tools/gen_docs.py" % rel)

    def test_readme_agents_and_concepts_name_only_real_verbs_and_flags(self):
        verbs = {k.split()[0] for k, _ in ENTRIES}
        known = set(GLOBALS) | FOREIGN | {"--help"} | {f for _, q in ENTRIES for f in flags_of(q)}
        bad = []
        for rel in ("README.md", "AGENTS.md", "docs/concepts.md"):
            text = read(rel)
            for fl in re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", text):
                if fl not in known:
                    bad.append("%s: %s" % (rel, fl))
            for v in re.findall(r"(?:`|^\s*|\$ )(?:\./)?awt ([a-z][a-z-]*)", text, re.M):
                if v not in verbs and v not in ("help", "migrate-wt", "migrate-paseo"):
                    bad.append("%s: awt %s" % (rel, v))
        self.assertEqual(sorted(set(bad)), [])

    def test_concepts_page_exists_and_stays_short(self):
        text = read("docs/concepts.md")
        for word in ("tree", "record", "store.db", "effect", "model", "ingest", "privacy"):
            self.assertIn(word, text.lower())
        self.assertLess(len(text.split()), 1200)


if __name__ == "__main__":
    unittest.main()
