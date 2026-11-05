"""Every ./awt command shown in the docs must use a real verb and real flags."""
import glob, os, re, subprocess, sys, tempfile, shutil, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AWT = os.path.join(REPO, "awt")


def run(*a):
    return subprocess.run([sys.executable, AWT] + list(a), capture_output=True, text=True, timeout=30)


def docs():
    for name in ["README.md"] + sorted(glob.glob(os.path.join(REPO, "docs", "*.md"))):
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

    def test_no_real_paths_or_hosts_in_docs(self):
        for src, text in docs():
            self.assertNotRegex(text, r"/Users/[a-z]+/")


if __name__ == "__main__":
    unittest.main()
