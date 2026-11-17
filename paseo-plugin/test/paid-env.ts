// Paid provider journeys (E-P8..E-P17): isolated stack. Test code only.
// Secrets are read at run time into the daemon's environment; they are never written to a file, a log or an error message.
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { homedir, tmpdir } from "node:os";
import { join, resolve } from "node:path";

export const REPO = resolve(import.meta.dirname, "..", "..");
export const PLUGIN = resolve(import.meta.dirname, "..");
export const RECORDER = join(PLUGIN, "test", "fake", "recorder");

const secrets: string[] = [];
export const scrub = (s: string) => secrets.reduce((a, x) => a.split(x).join("<secret>"), s);

export interface Stack { tmp: string; home: string; root: string; port: number; repo: string; hookLog: string; argvLog: string; env: NodeJS.ProcessEnv; wsId: string }

/** A short-lived Claude OAuth access token from the macOS keychain, kept in memory only. */
function claudeToken(): string | null {
  try {
    const out = execFileSync("security", ["find-generic-password", "-s", "Claude Code-credentials", "-a", process.env.USER ?? "", "-w"], { encoding: "utf8", timeout: 20_000, stdio: ["ignore", "pipe", "ignore"] });
    const o = JSON.parse(out).claudeAiOauth;
    if (!o?.accessToken || Date.now() > o.expiresAt - 600_000) return null;
    return o.accessToken as string;
  } catch { return null; }
}
function deepseekKey(): string | null {
  try { return JSON.parse(readFileSync(join(homedir(), ".pi", "agent", "auth.json"), "utf8")).deepseek?.key ?? null; } catch { return null; }
}
const free = () => new Promise<number>((ok) => { const s = createServer().listen(0, "127.0.0.1", () => { const p = (s.address() as any).port; s.close(() => ok(p)); }); });

export function paseo(st: Pick<Stack, "home" | "env">, ...a: string[]): string {
  try { return execFileSync("paseo", ["--home", st.home, ...a], { env: st.env, encoding: "utf8", timeout: 300_000, stdio: ["ignore", "pipe", "pipe"] }); }
  catch (e: any) { throw new Error(scrub(`paseo ${a.slice(0, 3).join(" ")} failed: ${String(e.stderr ?? e.message).slice(0, 600)}`)); }
}

/** The real stores whose size and mtime must not change (U3). */
export function realStores(): Record<string, string> {
  const h = homedir(), out: Record<string, string> = {};
  for (const p of [".paseo", ".claude/projects", ".claude/settings.json", ".local/share/opencode/opencode.db", ".config/opencode/plugins", ".pi/agent/sessions", ".pi/agent/extensions"]) {
    try { execFileSync("test", ["-e", join(h, p)]); out[p] = execFileSync("sh", ["-c", `find '${join(h, p)}' -maxdepth 1 -exec stat -f '%N %z %m' {} + | sort | md5`], { encoding: "utf8" }).trim(); } catch { out[p] = "absent"; }
  }
  return out;
}

export async function startStack(opts: { claude: boolean; deepseek: boolean; compactBrief?: boolean }): Promise<Stack> {
  const tmp = realpathSync(mkdtempSync(join(tmpdir(), "awtp-")));
  const home = join(tmp, "home"), root = join(tmp, "root"), repo = join(tmp, "parsekit");
  for (const d of [home, join(tmp, "bin"), join(tmp, "claude"), join(tmp, "xdg", "data"), join(tmp, "xdg", "config"), join(tmp, "pi"), repo]) mkdirSync(d, { recursive: true });
  const real = join(homedir(), ".paseo");
  if (existsSync(real) && realpathSync(real) === realpathSync(home)) throw new Error("refusing: home is the real ~/.paseo");
  // H7 shim: record argv + AWT_DIR/AWT_BY, then exec the real awt.
  const argv = join(tmp, "argv.jsonl");
  writeFileSync(join(tmp, "bin", "awt"), `#!/usr/bin/env python3
import json,os,sys,time
with open(${JSON.stringify(argv)},"a") as f:
    f.write(json.dumps({"ts":int(time.time()*1000),"argv":sys.argv[1:],"AWT_DIR":os.environ.get("AWT_DIR"),"AWT_BY":os.environ.get("AWT_BY"),"cwd":os.getcwd()})+"\\n")
os.execv(${JSON.stringify(join(REPO, "awt"))},[${JSON.stringify(join(REPO, "awt"))}]+sys.argv[1:])
`, { mode: 0o755 });
  const git = (...a: string[]) => execFileSync("git", ["-C", repo, "-c", "user.name=t", "-c", "user.email=t@e.invalid", ...a]);
  git("init", "-q"); writeFileSync(join(repo, "tokenizer.py"), "def tokenize(s):\n    return s.split()\n"); git("add", "tokenizer.py"); git("commit", "-qm", "init");

  const hookLog = join(tmp, "hooks.jsonl");
  const env: NodeJS.ProcessEnv = {
    HOME: tmp, TMPDIR: tmpdir(), TERM: "dumb", TZ: "UTC", LANG: "en_US.UTF-8", USER: process.env.USER,
    PATH: `${join(tmp, "bin")}:/Users/${process.env.USER}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin`,
    CLAUDE_CONFIG_DIR: join(tmp, "claude"), XDG_DATA_HOME: join(tmp, "xdg", "data"), XDG_CONFIG_HOME: join(tmp, "xdg", "config"), PI_CODING_AGENT_DIR: join(tmp, "pi"),
    AWT_BIN: join(REPO, "awt"), AWT_ROOT: root, AWT_TIMEOUT_MS: "20000", AWT_COMPACT_BRIEF: "1", AWT_HOOK_LOG: hookLog,
  };
  if (opts.compactBrief === false) delete env.AWT_COMPACT_BRIEF;
  if (opts.claude) { const t = claudeToken(); if (!t) throw new Error("no usable Claude credential in the keychain"); secrets.push(t); env.CLAUDE_CODE_OAUTH_TOKEN = t; }
  if (opts.deepseek) { const k = deepseekKey(); if (!k) throw new Error("no deepseek credential"); secrets.push(k); env.DEEPSEEK_API_KEY = k; }
  const port = await free();
  writeFileSync(join(home, "config.json"), JSON.stringify({
    version: 1, pluginsEnabled: true,
    daemon: { listen: `127.0.0.1:${port}`, relay: { enabled: false }, mcp: { injectIntoAgents: true } },
    features: { dictation: { enabled: false } },
  }));
  const st: Stack = { tmp, home, root, port, repo, hookLog, argvLog: argv, env, wsId: "" };
  paseo(st, "daemon", "start", "--timeout", "90");
  paseo(st, "plugin", "install", PLUGIN);
  paseo(st, "plugin", "install", RECORDER);
  paseo(st, "daemon", "stop");
  paseo(st, "daemon", "start", "--timeout", "90");
  const ws = JSON.parse(paseo(st, "workspace", "create", "--isolation", "local", "--path", repo, "--title", "main", "--json"));
  st.wsId = (Array.isArray(ws) ? ws[0] : ws).workspaceId ?? JSON.parse(paseo(st, "workspace", "ls", "--json"))[0].workspaceId;
  return st;
}

export function stopStack(st: Stack, keep = false) {
  try { paseo(st, "daemon", "stop"); } catch {
    try { const f = join(st.home, "paseo.pid"); if (existsSync(f)) process.kill(Number(/"?pid"?\D*(\d+)/.exec(readFileSync(f, "utf8"))?.[1])); } catch {}
  }
  if (!keep) rmSync(st.tmp, { recursive: true, force: true });
}

if (process.argv[1]?.endsWith("paid-env.ts") && process.argv[2] === "up") {
  const st = await startStack({ claude: true, deepseek: true });
  console.log(JSON.stringify({ tmp: st.tmp, home: st.home, port: st.port, ws: st.wsId }));
}
