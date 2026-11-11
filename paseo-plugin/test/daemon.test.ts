// Tier 2: a real Paseo daemon in a temp home, a scripted ACP agent, the real awt.
// Gated: AWT_E2E_PASEO=1 npm test. Never touches ~/.paseo.
import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const ON = process.env.AWT_E2E_PASEO === "1";
const REPO = resolve(import.meta.dirname, "..", "..");
const PLUGIN = resolve(import.meta.dirname, "..");
const FAKE = join(PLUGIN, "test", "fake", "acp_agent.py");

let tmp = "", home = "", repo = "", root = "", env: NodeJS.ProcessEnv = {}, wsId = "";

const paseo = (...a: string[]) => execFileSync("paseo", ["--home", home, ...a], { env, encoding: "utf8", timeout: 120_000 });
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
  const port = await free();
  writeFileSync(join(home, "config.json"), JSON.stringify({
    version: 1, pluginsEnabled: true,
    daemon: { listen: `127.0.0.1:${port}`, mcp: { injectIntoAgents: false } },
    agents: { providers: { fake: { extends: "acp", label: "Fake", command: ["python3", FAKE] } } },
  }));
  paseo("daemon", "start", "--timeout", "90");
  paseo("plugin", "install", PLUGIN);
  paseo("daemon", "restart");
  const ws = JSON.parse(paseo("workspace", "create", "--isolation", "local", "--path", repo, "--title", "main", "--json"));
  wsId = (Array.isArray(ws) ? ws[0] : ws).workspaceId ?? JSON.parse(paseo("workspace", "ls", "--json"))[0].workspaceId;
});

after(() => {
  if (!ON) return;
  try { paseo("daemon", "stop"); } catch {}
  rmSync(tmp, { recursive: true, force: true });
});

test("D1 the plugin loads in a real daemon", { skip: !ON }, () => {
  assert.match(paseo("plugin", "ls"), /awt\s+running/);
});

test("D2 a new agent gets its node, env, and an awt on PATH that reads it", { skip: !ON }, () => {
  const id = run("first", 'RUN: env | grep ^AWT_ ; awt note "hello from agent" ; awt resume | head -3');
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

test("D3 the agent is nudged once after a turn with no handoff", { skip: !ON }, () => {
  const id = agents().find((a) => a.name === "first").id;
  const out = logs(id);
  assert.equal((out.match(/Before you stop, record where things stand/g) ?? []).length >= 1, true);
});

test("D4 a handoff recorded during the turn suppresses the nudge", { skip: !ON }, () => {
  const id = run("second", 'RUN: awt state --now "did x" --next "do y"');
  assert.doesNotMatch(logs(id), /Before you stop, record where things stand/);
});

test("D5 reopening an agent keeps the same node", { skip: !ON }, () => {
  const id = agents().find((a) => a.name === "second").id;
  const before = nodes().filter((x) => x.kind === "agent").length;
  paseo("send", id, "RUN: echo again");
  assert.equal(nodes().filter((x) => x.kind === "agent").length, before);
});

test("M11 migrate-paseo against the real daemon is idempotent and lossless", { skip: !ON }, () => {
  const mroot = join(tmp, "mroot");
  const mig = () => execFileSync(join(REPO, "migrate-paseo"), ["--home", home, mroot], { env: { ...env, AWT_ROOT: mroot }, encoding: "utf8" });
  mig();
  const a = JSON.parse(awt(mroot, "list", "nodes", "--all", "--json"));
  const keys = a.map((x: any) => x.key);
  assert.ok(keys.includes(`paseo:workspace/${wsId}`));
  for (const ag of agents()) assert.ok(keys.includes(`paseo:agent/${ag.id}`), ag.id);
  mig();
  assert.equal(JSON.parse(awt(mroot, "list", "nodes", "--all", "--json")).length, a.length);
});
