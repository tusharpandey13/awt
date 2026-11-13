// Daemon-gated journeys E-R9..E-R16, E-R22 of docs/e2e-active-recall.md.
// Gated: AWT_E2E_PASEO=1. An isolated daemon (own home, port, AWT_ROOT under a temp dir) and a fake ACP agent; no model tokens.
// H2 path: plugin timeline items are NOT in `paseo logs`, so receipts are read with @getpaseo/client (timeline.refetch).
import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { createPaseoClient } from "@getpaseo/client";

const ON = process.env.AWT_E2E_PASEO === "1";
const REPO = resolve(import.meta.dirname, "..", "..");
const PLUGIN = resolve(import.meta.dirname, "..");
const FAKE = join(PLUGIN, "test", "fake", "acp_agent.py");
const PRE_FEATURE = "a35fea8";

let tmp = "", home = "", root = "", wire = "", port = 0, base: NodeJS.ProcessEnv = {};
let w1 = "", w2 = "", dRule = "";

const paseo = (...a: string[]) => execFileSync("paseo", ["--home", home, ...a], { env: base, encoding: "utf8", timeout: 120_000 });
const awt = (dir: string, ...a: string[]) => execFileSync(join(REPO, "awt"), ["--dir", dir, ...a], { env: base, encoding: "utf8" });
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const free = () => new Promise<number>((ok) => { const s = createServer().listen(0, "127.0.0.1", () => { const p = (s.address() as any).port; s.close(() => ok(p)); }); });
const nodes = (): any[] => JSON.parse(awt(root, "list", "nodes", "--all", "--json"));
const agents = (): any[] => JSON.parse(paseo("ls", "-a", "--json"));
const idOf = (title: string) => agents().find((a) => a.name === title).id as string;
const node = (id: string) => nodes().find((x) => x.key === `paseo:agent/${id}`);
const nodeDir = (id: string) => join(root, node(id).path);
const logs = (id: string) => paseo("logs", id);
const rows = (id: string, type: string) => JSON.parse(awt(nodeDir(id), "list", type, "--all", "--json")) as any[];
const wireText = () => (existsSync(wire) ? readFileSync(wire, "utf8") : "");

/** Start the daemon with the shared env plus `extra`; `unset` removes keys. A restart that changes env must be stop then start. */
function startDaemon(extra: Record<string, string> = {}, unset: string[] = []) {
  const e: NodeJS.ProcessEnv = { ...base, AWT_RELATED: "2", AWT_FAKE_WIRE: wire, ...extra };
  for (const k of unset) delete e[k];
  try { paseo("daemon", "stop"); } catch {}
  execFileSync("paseo", ["--home", home, "daemon", "start", "--timeout", "90"], { env: e, encoding: "utf8", timeout: 120_000 });
}

function run(title: string, prompt: string, ws = w1): string {
  try { paseo("run", "--provider", "fake", "--workspace", ws, "--title", title, prompt); } catch (e) { if (!title.startsWith("fail")) throw e; }
  return idOf(title);
}
const send = (id: string, prompt: string) => { try { paseo("send", id, prompt); } catch (e) { if (!/FAIL:/.test(prompt)) throw e; } };

// H2: plugin timeline items via the client.
function collect(x: any, out: any[]) {
  if (Array.isArray(x)) { for (const y of x) collect(y, out); return; }
  if (x && typeof x === "object") {
    if (x.type === "plugin" && x.kind) out.push(x);
    else if (x.item && x.item.type === "plugin") out.push(x.item);
    else for (const v of Object.values(x)) collect(v, out);
  }
}
async function timelineRaw(id: string): Promise<any> {
  const c = createPaseoClient({ url: `ws://127.0.0.1:${port}/ws`, connectTimeoutMs: 8000 });
  await c.connect();
  try { return await c.agents.ref(id).timeline.refetch({ direction: "tail", limit: 200 }); } finally { await c.close(); }
}
async function receipts(id: string): Promise<any[]> {
  const out: any[] = [];
  collect(await timelineRaw(id), out);
  return out.filter((i) => i.kind === "awt.receipt");
}
/** H3: poll every 250 ms until n receipts (or at least n), 15 s cap. */
async function waitReceipts(id: string, n: number): Promise<any[]> {
  const end = Date.now() + 15_000;
  let r: any[] = [];
  while (Date.now() < end) { r = await receipts(id); if (r.length >= n) return r; await sleep(250); }
  assert.fail(`expected ${n} receipt(s) for ${id} within 15 s, saw ${r.length}`);
}
const count = (r: any, t: string) => r.data.counts[t] ?? 0;

before(async () => {
  if (!ON) return;
  tmp = realpathSync(mkdtempSync(join(tmpdir(), "awtr-")));
  home = join(tmp, "home"); root = join(tmp, "root"); wire = join(tmp, "wire.jsonl");
  mkdirSync(home); mkdirSync(join(tmp, "bin"));
  symlinkSync(join(REPO, "awt"), join(tmp, "bin", "awt"));
  base = { ...process.env, HOME: tmp, TZ: "UTC", AWT_BIN: join(REPO, "awt"), AWT_ROOT: root, AWT_TIMEOUT_MS: "20000", PATH: `${join(tmp, "bin")}:${process.env.PATH}` };
  for (const k of Object.keys(base)) if (k.startsWith("PASEO_") || (k.startsWith("AWT_") && !["AWT_BIN", "AWT_ROOT", "AWT_TIMEOUT_MS"].includes(k)) || k === "CLAUDECODE") delete base[k];
  // pre-flight: never the real home or root
  assert.ok(home.startsWith(tmp) && root.startsWith(tmp) && home !== join(process.env.HOME ?? "", ".paseo"));
  const r1 = join(tmp, "parsekit"), r2 = join(tmp, "ledgerline");
  for (const r of [r1, r2]) { mkdirSync(r); execFileSync("git", ["init", "-q", r]); }
  port = await free();
  writeFileSync(join(home, "config.json"), JSON.stringify({
    version: 1, pluginsEnabled: true,
    daemon: { listen: `127.0.0.1:${port}`, relay: { enabled: false }, mcp: { injectIntoAgents: false } },
    features: { dictation: { enabled: false } },
    agents: { providers: { fake: { extends: "acp", label: "Fake", command: ["python3", FAKE] } } },
  }));
  startDaemon();
  paseo("plugin", "install", PLUGIN);
  startDaemon();
  const mk = (p: string, title: string) => { const ws = JSON.parse(paseo("workspace", "create", "--isolation", "local", "--path", p, "--title", title, "--json")); return (Array.isArray(ws) ? ws[0] : ws).workspaceId as string; };
  w1 = mk(r1, "main"); w2 = mk(r2, "ledger");
  // W2's node is created by the plugin when an agent opens in it.
  run("seed2", "ping", w2);
  const n2 = nodes().find((x) => x.key === `paseo:workspace/${w2}`);
  assert.ok(n2, "plugin created the W2 workspace node");
  const out = awt(join(root, n2.path), "decide", "Retry gateway calls with exponential backoff and full jitter", "--why", "Fixed backoff synchronised the clients and overloaded the gateway", "--tag", "rule");
  dRule = /^(d-[0-9a-f]{8}) /.exec(out)![1];
  writeFileSync(wire, ""); // only count what later journeys send
});

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
after(() => {
  const t = tmp;
  cleanup();
  if (ON && t) { let left = ""; try { left = execFileSync("pgrep", ["-f", join(t, "home")], { encoding: "utf8" }); } catch {} assert.equal(left.trim(), "", "no process survives with the temp home in argv"); }
});

let env1 = "", rec1 = "";

test("E-R9 plugin from the worktree, prompt block, env forwarding", { skip: !ON }, async () => {
  // 1
  const ls = paseo("plugin", "ls");
  assert.match(ls, /awt\s+running/);
  const m = /(\/\S*paseo-plugin)\b/.exec(ls);
  if (m) assert.equal(realpathSync(m[1]), PLUGIN);
  // 2
  env1 = run("env1", "RUN: env | grep -E '^AWT_(RELATED|DIR|BY)=' | sort");
  const out = logs(env1);
  assert.match(out, /AWT_RELATED=2/);
  assert.match(out, new RegExp(`AWT_BY=${env1}`));
  assert.ok(out.includes(`AWT_DIR=${root}/`), "AWT_DIR under AWT_ROOT");
  // 3
  paseo("send", env1, 'RUN: awt decide "Use fixed backoff for gateway calls" --why "simplest for the gateway client"');
  const o3 = logs(env1);
  assert.match(o3, /decided/);
  const rel = o3.split("\n").filter((l) => /related: /.test(l));
  assert.ok(rel.length >= 1 && rel.length <= 2, `related lines: ${rel.length}`);
  assert.ok(rel.some((l) => l.includes(dRule)), "D_RULE (other workspace) is related");
  // 4: the system prompt is not forwarded over ACP (the wire has no [awt]); `paseo inspect --json` exposes it
  const env2 = run("env2", "ping");
  assert.ok(!wireText().includes("[awt]"), "the ACP wire carries no system prompt");
  const block = async (id: string): Promise<string> => { const sp = (await timelineRaw(id)).agent?.persistence?.metadata?.systemPrompt; assert.ok(typeof sp === "string" && sp.includes("[awt]"), `[awt] block in the agent snapshot of ${id}`); return sp; };
  const b1 = await block(env1), b2 = await block(env2);
  assert.ok(b1.length <= 700, `block length ${b1.length}`);
  assert.ok(b1.includes("find --like"));
  assert.ok(b1.includes("call it again after your context is compacted"), "SPEC R5: prompt-line path");
  assert.equal(b1, b2, "byte-identical for env1 and env2");
});

test("E-R9 step 5: without AWT_RELATED nothing is invented", { skip: !ON }, () => {
  startDaemon({}, ["AWT_RELATED"]);
  const id = run("env3", "RUN: env | grep -c ^AWT_RELATED=");
  assert.match(logs(id), /exit=1 0\b/);
  startDaemon(); // back to the shared daemon env
});

test("E-R10 a turn that records a decision gets one receipt with the right counts", { skip: !ON }, async () => {
  // 0: probe H2
  const raw = await timelineRaw(env1);
  const items: any[] = []; collect(raw, items);
  assert.ok(items.length >= 0);
  console.log(`H2 path: @getpaseo/client timeline.refetch; plugin items seen on env1: ${items.length}`);
  // 1
  rec1 = run("rec1", 'RUN: awt decide "Retry with full jitter" --why "Fixed backoff synchronised the clients" ; awt note "soak run queued"');
  const log = logs(rec1);
  const dId = /(d-[0-9a-f]{8}) decided/.exec(log)![1];
  const nId = /(n-[0-9a-f]{8})/.exec(log)![1];
  const r = await waitReceipts(rec1, 1);
  assert.equal(r.length, 1);
  const it = r[0];
  assert.equal(it.version, 1);
  assert.equal(it.data.node, node(rec1).name);
  assert.deepEqual(it.data.counts, { decision: 1, note: 1, state: 1 });
  assert.equal(it.data.auto, true);
  assert.equal(it.data.empty, false);
  assert.ok(it.data.ids.includes(dId) && it.data.ids.includes(nId) && it.data.ids.length <= 5, JSON.stringify(it.data.ids));
  // ordering: after the turn's last assistant message
  const all = JSON.stringify(await timelineRaw(rec1));
  assert.ok(all.lastIndexOf('"awt.receipt"') > all.lastIndexOf('"assistant_message"'), "receipt after the last assistant_message");
  // 2
  const dts = rows(rec1, "decisions")[0].ts;
  const grouped: Record<string, number> = {};
  for (const x of JSON.parse(awt(nodeDir(rec1), "list", "--since", dts, "--down", "--json"))) {
    if (x.type === "node" || (x.by === "paseo-plugin" && !(x.type === "state" && x.scope === "auto"))) continue;
    grouped[x.type] = (grouped[x.type] ?? 0) + 1;
  }
  assert.deepEqual(grouped, it.data.counts);
  // 3
  const autoBefore = rows(rec1, "state").filter((s) => s.scope === "auto").length;
  paseo("send", rec1, 'RUN: awt state --now "jitter merged" --next "soak"');
  const r2 = await waitReceipts(rec1, 2);
  assert.equal(r2.length, 2);
  assert.equal(count(r2[1], "state"), 1);
  assert.equal(r2[1].data.auto, false);
  assert.equal(rows(rec1, "state").filter((s) => s.scope === "auto").length, autoBefore);
  // 4
  paseo("send", rec1, "RUN: for i in 1 2 3 4 5 6 7; do awt note \"n$i\"; done");
  const r3 = await waitReceipts(rec1, 3);
  assert.equal(r3.length, 3);
  assert.equal(count(r3[2], "note"), 7);
  assert.equal(r3[2].data.ids.length, 5);
  // 5
  await sleep(2000);
  assert.equal((await receipts(rec1)).length, 3, "one receipt per turn");
});

test("E-R11 a turn that stores nothing gets an empty receipt", { skip: !ON }, async () => {
  const id = run("quiet", "ping");
  const r = await waitReceipts(id, 1);
  assert.equal(r[0].data.auto, true);
  assert.equal(count(r[0], "state"), 1);
  assert.equal(r[0].data.empty, false);
  paseo("send", id, "ping");
  const r2 = await waitReceipts(id, 2);
  assert.equal(r2[1].data.empty, true);
  assert.deepEqual(r2[1].data.counts, {});
  assert.deepEqual(r2[1].data.ids, []);
  assert.equal(r2[1].data.auto, false);
  assert.equal(rows(id, "state").length, 1);
});

test("E-R12 AWT_RECEIPT=changes, AWT_RECEIPT=0, AWT_AUTO_HANDOFF=0", { skip: !ON }, async () => {
  startDaemon({ AWT_RECEIPT: "changes" });
  const chg = run("chg", 'RUN: awt note "chg1"');
  assert.equal((await waitReceipts(chg, 1)).length, 1);
  send(chg, "ping"); // stores only the stand-in: hidden under `changes` (SPEC.md resolution 7)
  await sleep(15_000);
  assert.equal((await receipts(chg)).length, 1);
  const quiet = run("chgq", "ping"); // first turn is also stand-in only
  await sleep(15_000);
  assert.equal((await receipts(quiet)).length, 0);

  startDaemon({ AWT_RECEIPT: "0" });
  const off = run("off", 'RUN: awt note "silent"');
  await sleep(15_000);
  assert.equal((await receipts(off)).length, 0);
  assert.ok(rows(off, "notes").some((n) => n.text?.includes?.("silent") || JSON.stringify(n).includes("silent")));
  assert.ok(rows(off, "state").some((s) => s.scope === "auto"));

  startDaemon({ AWT_AUTO_HANDOFF: "0" });
  const noauto = run("noauto", "ping");
  const r = await waitReceipts(noauto, 1);
  assert.equal(r[0].data.empty, true);
  assert.equal(r[0].data.auto, false);
  startDaemon();
});

test("E-R13 receipts for a subagent; the parent counts its descendants", { skip: !ON }, async () => {
  const cmd = `paseo --home ${home} run --provider fake --workspace ${w1} --title kid --label paseo.parent-agent-id=$AWT_BY 'RUN: awt note "kid finding"' >/dev/null; awt note "boss done"`;
  const boss = run("boss", "RUN: " + cmd);
  const kid = idOf("kid");
  const kr = await waitReceipts(kid, 1);
  assert.equal(count(kr[0], "note"), 1);
  assert.equal(count(kr[0], "state"), 0);
  assert.equal(kr[0].data.auto, false);
  assert.equal(kr[0].data.node, node(kid).name);
  assert.ok(node(kid).path.startsWith(node(boss).path + "/"), "kid node under boss node");
  const br = await waitReceipts(boss, 1);
  assert.equal(count(br[0], "note"), 2);
  assert.equal(count(br[0], "state"), 1);
  assert.equal(br[0].data.auto, true);
  const kidNote = rows(kid, "notes").find((n) => JSON.stringify(n).includes("kid finding")).id;
  assert.ok(br[0].data.ids.includes(kidNote));
});

test("E-R14 receipts for canceled and failed turns", { skip: !ON }, async () => {
  paseo("run", "--no-wait", "--provider", "fake", "--workspace", w1, "--title", "cxl", 'RUN: awt note "before cancel"; sleep 30');
  const id = idOf("cxl");
  const end = Date.now() + 20_000;
  while (Date.now() < end) { try { if (rows(id, "notes").some((n) => JSON.stringify(n).includes("before cancel"))) break; } catch {} await sleep(250); }
  paseo("stop", id);
  const r = await waitReceipts(id, 1);
  assert.equal(count(r[0], "note"), 1);
  assert.equal(count(r[0], "state"), 0);
  const f = run("fail1", 'FAIL: awt note "before fail"');
  const fr = await waitReceipts(f, 1);
  assert.equal(count(fr[0], "note"), 1);
  const st = JSON.parse(paseo("ls", "-a", "--json")).find((a: any) => a.id === f);
  console.log(`failed-turn agent status: ${st?.status}`);
});

test("E-R15 receipts are not in the provider's input (ACP)", { skip: !ON }, async () => {
  const pat = /awt\.receipt|awt ·|nothing stored this turn/;
  // A fresh agent on the current plugin process (receipts of agents opened before a restart are lost, see report).
  const id = run("rec2", 'RUN: awt note "ctl"');
  assert.equal((await waitReceipts(id, 1)).length, 1, "positive control: a receipt exists in the timeline");
  const w = wireText();
  assert.ok(w.includes('"session/prompt"'), "positive control: the wire holds prompts");
  assert.doesNotMatch(w, pat);
  startDaemon();
  paseo("send", id, "ping"); // resume / session/load path
  const w2t = wireText();
  assert.ok(w2t.length > w.length && w2t.includes('"session/load"') || w2t.length > w.length, "the resumed turn reached the provider");
  assert.doesNotMatch(w2t, pat);
});

test("E-R16 receipts render (manual)", { skip: "manual: see docs/e2e-active-recall.md E-R16; needs the Paseo app on the D0 daemon" }, () => {});

test("E-R22 plugin upgrade over an existing daemon tree", { skip: !ON }, async () => {
  const old = join(tmp, "oldplugin");
  mkdirSync(old);
  execFileSync("sh", ["-c", `git -C ${REPO} archive ${PRE_FEATURE} paseo-plugin | tar -x -C ${old} --strip-components=1`]);
  execFileSync("npm", ["ci", "--prefer-offline", "--no-audit", "--no-fund"], { cwd: old, stdio: "ignore", timeout: 300_000 });
  paseo("plugin", "remove", "awt");
  paseo("plugin", "install", old);
  startDaemon();
  const o = run("old1", 'RUN: awt note "before upgrade"');
  assert.equal((await receipts(o)).length, 0, "the old plugin writes no receipts");
  const n0 = nodes().filter((x) => x.key === `paseo:agent/${o}`).length;
  assert.equal(n0, 1);
  paseo("plugin", "remove", "awt");
  paseo("plugin", "install", PLUGIN);
  startDaemon();
  paseo("send", o, 'RUN: awt note "after upgrade"');
  const r = await waitReceipts(o, 1);
  assert.equal(r.length, 1);
  assert.equal(count(r[0], "note"), 1);
  assert.equal(nodes().filter((x) => x.key === `paseo:agent/${o}`).length, 1);
  const doc = awt(root, "doctor");
  assert.match(doc, /0 quarantined/);
  assert.doesNotMatch(doc, /\bfail\b/);
});
