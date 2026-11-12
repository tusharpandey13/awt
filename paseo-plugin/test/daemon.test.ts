// Tier 2: a real Paseo daemon in a temp home, a scripted ACP agent, the real awt.
// Gated: AWT_E2E_PASEO=1 npm test. Never touches ~/.paseo.
import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";

const ON = process.env.AWT_E2E_PASEO === "1";
const REPO = resolve(import.meta.dirname, "..", "..");
const PLUGIN = resolve(import.meta.dirname, "..");
const FAKE = join(PLUGIN, "test", "fake", "acp_agent.py");

let tmp = "", home = "", repo = "", root = "", env: NodeJS.ProcessEnv = {}, wsId = "";

const paseo = (...a: string[]) => execFileSync("paseo", ["--home", home, ...a], { env, encoding: "utf8", timeout: 120_000 });
const settle = () => { try { for (const a of agents()) paseo("wait", a.id, "--timeout", "30"); } catch {} };
const awt = (dir: string, ...a: string[]) => execFileSync(join(REPO, "awt"), ["--dir", dir, ...a], { env, encoding: "utf8" });
const free = () => new Promise<number>((ok) => { const s = createServer().listen(0, "127.0.0.1", () => { const p = (s.address() as any).port; s.close(() => ok(p)); }); });
const nodes = (): any[] => JSON.parse(awt(root, "list", "nodes", "--all", "--json"));
const logs = (id: string) => paseo("logs", id);
const agents = (): any[] => JSON.parse(paseo("ls", "-a", "--json"));
function run(title: string, prompt: string): string {
  paseo("run", "--provider", "fake", "--workspace", wsId, "--title", title, prompt);
  const id = agents().find((a) => a.name === title).id;
  return id;
}

before(async () => {
  if (!ON) return;
  tmp = realpathSync(mkdtempSync(join(tmpdir(), "awtd-")));
  home = join(tmp, "home"); repo = join(tmp, "parsekit"); root = join(tmp, "root");
  mkdirSync(home); mkdirSync(repo); mkdirSync(join(tmp, "bin"));
  symlinkSync(join(REPO, "awt"), join(tmp, "bin", "awt"));
  env = { ...process.env, HOME: tmp, AWT_BIN: join(REPO, "awt"), AWT_ROOT: root, AWT_TIMEOUT_MS: "20000", PATH: `${join(tmp, "bin")}:${process.env.PATH}` };
  execFileSync("git", ["init", "-q", repo]);
  for (const k of Object.keys(env)) if (k.startsWith("PASEO_")) delete env[k];
  const port = await free();
  writeFileSync(join(home, "config.json"), JSON.stringify({
    version: 1, pluginsEnabled: true,
    daemon: { listen: `127.0.0.1:${port}`, relay: { enabled: false }, mcp: { injectIntoAgents: false } },
    features: { dictation: { enabled: false } },
    agents: { providers: { fake: { extends: "acp", label: "Fake", command: ["python3", FAKE] } } },
  }));
  paseo("daemon", "start", "--timeout", "90");
  paseo("plugin", "install", PLUGIN);
  paseo("daemon", "restart");
  const ws = JSON.parse(paseo("workspace", "create", "--isolation", "local", "--path", repo, "--title", "main", "--json"));
  wsId = (Array.isArray(ws) ? ws[0] : ws).workspaceId ?? JSON.parse(paseo("workspace", "ls", "--json"))[0].workspaceId;
});

// Stop the temp daemon; if that fails, kill it by the pid in its own home, then remove the home.
function cleanup() {
  if (!tmp) return;
  try { paseo("daemon", "stop"); } catch {
    try {
      const f = join(home, "paseo.pid");
      if (existsSync(f)) process.kill(Number(/"?pid"?\D*(\d+)/.exec(readFileSync(f, "utf8"))?.[1]));
    } catch {}
  }
  rmSync(tmp, { recursive: true, force: true });
  tmp = "";
}
for (const sig of ["SIGINT", "SIGTERM"] as const) process.once(sig, () => { cleanup(); process.exit(1); });
after(cleanup);

let firstId = "";

test("E0 the plugin loads in a real daemon", { skip: !ON }, () => {
  assert.match(paseo("plugin", "ls"), /awt\s+running/);
});

test("E1 a new agent gets its node, env, and an awt on PATH that reads it", { skip: !ON }, () => {
  firstId = run("first", 'RUN: env | grep ^AWT_ ; awt note "hello from agent" ; awt resume | head -3');
  const id = firstId;
  const out = logs(id);
  assert.match(out, new RegExp(`AWT_BY=${id}`));
  assert.match(out, /AWT_DIR=.*\/tasks\/main\/agents\/first/);
  assert.match(out, /# awt task/);
  const n = nodes();
  assert.equal(n.filter((x) => x.key === `paseo:agent/${id}`).length, 1);
  assert.ok(n.some((x) => x.kind === "workspace" && x.key === `paseo:workspace/${wsId}`));
  assert.ok(n.some((x) => x.key === `paseo:task/${wsId}/main`));
  assert.match(awt(root, "doctor"), /0 quarantined/);
});

test("E2 awt note from the agent lands in its node, not the task's", { skip: !ON }, () => {
  const events = (d: string) => readFileSync(join(d, ".awt", "events.jsonl"), "utf8");
  const dir = /AWT_DIR=(\S+)/.exec(logs(firstId))![1];
  const task = dirname(dirname(dir));
  assert.match(task, /\/tasks\/main$/);
  assert.match(events(dir), /hello from agent/);
  assert.doesNotMatch(events(task), /hello from agent/);
});

test("E7 a turn with no handoff leaves the agent's last reply as state in scope auto, and no prompt in the chat", { skip: !ON }, () => {
  settle();
  assert.doesNotMatch(logs(firstId), /Before you stop, record where things stand/);
  const dir = /AWT_DIR=(\S+)/.exec(logs(firstId))![1];
  const st = JSON.parse(awt(dir, "list", "state", "--all", "--json"));
  assert.equal(st.length >= 1, true);
  assert.equal(st.at(-1).scope, "auto");
  assert.match(st.at(-1).now, /^\[auto\] exit=0 /);
});

test("E8 a handoff recorded during the turn means no auto state", { skip: !ON }, () => {
  const id = run("second", 'RUN: awt state --now "did x" --next "do y"');
  settle();
  const dir = nodes().find((x) => x.key === `paseo:agent/${id}`)!;
  const st = JSON.parse(awt(join(root, dir.path), "list", "state", "--all", "--json"));
  assert.deepEqual(st.map((x: any) => x.scope), ["main"]);
});

test("E4 restarting the daemon and resuming an agent keeps the same node", { skip: !ON }, () => {
  const id = agents().find((a) => a.name === "second").id;
  const before = nodes().filter((x) => x.kind === "agent").length;
  paseo("daemon", "restart", "--timeout", "90");
  paseo("send", id, "RUN: echo again");
  settle();
  assert.equal(nodes().filter((x) => x.kind === "agent" && x.key === `paseo:agent/${id}`).length, 1);
  assert.equal(nodes().filter((x) => x.kind === "agent").length, before);
});

test("E3 an agent started with the parent label gets its node under the parent's node", { skip: !ON }, () => {
  const parent = agents().find((a) => a.name === "first").id;
  paseo("run", "--provider", "fake", "--workspace", wsId, "--title", "kid", "--label", `paseo.parent-agent-id=${parent}`, 'RUN: env | grep ^AWT_ ; awt resume | head -3');
  const kid = agents().find((a) => a.name === "kid").id;
  settle();
    const parentDir = join(root, nodes().find((x) => x.key === `paseo:agent/${parent}`).path); // the parent's log is gone after the daemon restart in E4
  const out = logs(kid);
  const kidDir = /AWT_DIR=(\S+)/.exec(out)![1];
  assert.match(out, new RegExp(`AWT_BY=${kid}`));
  assert.equal(dirname(dirname(kidDir)), parentDir, "child node sits in the parent agent's agents/ dir");
  const n = nodes();
  assert.equal(n.filter((x) => x.key === `paseo:agent/${kid}`).length, 1);
  assert.match(awt(root, "doctor"), /0 quarantined/);
  // The first row of the child's log is its node row, under the parent; no "missing parent" note was needed.
  assert.doesNotMatch(readFileSync(join(kidDir, ".awt", "events.jsonl"), "utf8"), /started by agent/);
});

test("M11 migrate-paseo reads the on-disk store written by a real daemon, idempotently", { skip: !ON }, () => {
  const mroot = join(tmp, "mroot");
  const mig = () => execFileSync(join(REPO, "migrate-paseo"), ["--home", home, mroot], { env: { ...env, AWT_ROOT: mroot }, encoding: "utf8" });
  // The store is the one a real daemon wrote, so this checks the reader against the real on-disk format.
  mig();
  const a = JSON.parse(awt(mroot, "list", "nodes", "--all", "--json"));
  const keys = a.map((x: any) => x.key);
  assert.ok(keys.includes(`paseo:workspace/${wsId}`));
  for (const ag of agents()) assert.ok(keys.includes(`paseo:agent/${ag.id}`), ag.id);
  mig();
  assert.equal(JSON.parse(awt(mroot, "list", "nodes", "--all", "--json")).length, a.length);
});
