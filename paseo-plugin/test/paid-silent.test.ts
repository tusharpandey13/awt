// Silent context after compaction, journey test on Claude Haiku only (tests/TEST-SPEC.md, "Compaction context", gated part).
// Gated: AWT_E2E_PAID=1 (owner approval; spends tokens). Real Claude Code through an isolated Paseo daemon, hook installed in an isolated CLAUDE_CONFIG_DIR.
// AWT_SILENT_ONLY="W,C,Wc,Cc" picks cells (W waiting, C continuing, lower-case c = control without the hook); AWT_SILENT_RUNS runs per cell (default 1);
// AWT_SILENT_CAP is the total dollar cap (default 0.50). Results: $AWT_PAID_OUT (default /tmp/awt-logs/paid-results.jsonl).
import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { execFile, execFileSync } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { promisify } from "node:util";
import { createPaseoClient } from "@getpaseo/client";
import { type Stack, REPO, paseo, realStores, scrub, startStack, stopStack } from "./paid-env.js";

const ON = process.env.AWT_E2E_PAID === "1";
const ONLY = (process.env.AWT_SILENT_ONLY ?? "W,C,Wc,Cc").split(",").map((x) => x.trim());
const RUNS = Number(process.env.AWT_SILENT_RUNS ?? "1");
const CAP = Number(process.env.AWT_SILENT_CAP ?? "0.5");
const OUT = process.env.AWT_PAID_OUT ?? "/tmp/awt-logs/paid-results.jsonl";
const MODEL = "claude-haiku-5-5"; // the only model this file may use
const FRAME = "awt record for this task";
const pexec = promisify(execFile);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

let st: Stack;
let stores0: Record<string, string> = {};
let spent = 0;
const px = (...a: string[]) => paseo(st, ...a);
const awt = (...a: string[]) => execFileSync(join(REPO, "awt"), a, { env: st.env, encoding: "utf8" });
const agents = (): any[] => JSON.parse(px("ls", "-a", "--json"));
const idOf = (title: string) => agents().find((a) => a.name === title)?.id as string;
const nodeDir = (id: string) => { const n = JSON.parse(awt("--dir", st.root, "list", "nodes", "--all", "--json")).find((x: any) => x.key === `paseo:agent/${id}`); return n ? join(st.root, n.path) : ""; };

async function settle(id: string) {
  for (let i = 0; i < 12; i++) {
    let pend: any[] = [];
    try { pend = JSON.parse(px("permit", "ls", "--json") || "[]").filter((p: any) => p.agentId === id); } catch {}
    if (pend.length === 0) { try { await pexec("paseo", ["--home", st.home, "wait", id, "--timeout", "120"], { env: st.env, timeout: 150_000 }); } catch {} if (!JSON.parse(px("permit", "ls", "--json") || "[]").some((p: any) => p.agentId === id)) return; }
    for (const p of pend) { try { px("permit", "allow", id, p.id); } catch {} }
  }
}
async function run(title: string, prompt: string): Promise<string> {
  try { await pexec("paseo", ["--home", st.home, "run", "--provider", "claude", "--model", MODEL, "--workspace", st.wsId, "--title", title, prompt], { env: st.env, timeout: 300_000, encoding: "utf8" }); }
  catch (e: any) { if (!idOf(title)) throw new Error(scrub(`run ${title}: ${String(e.stderr ?? e.message).slice(0, 300)}`)); }
  await settle(idOf(title));
  return idOf(title);
}
async function send(id: string, prompt: string) {
  try { await pexec("paseo", ["--home", st.home, "send", id, prompt], { env: st.env, timeout: 300_000, encoding: "utf8" }); } catch {}
  await settle(id);
}
async function timeline(id: string): Promise<any> {
  const c = createPaseoClient({ url: `ws://127.0.0.1:${st.port}/ws`, connectTimeoutMs: 8000 });
  await c.connect();
  try { return await c.agents.ref(id).timeline.refetch({ direction: "tail", limit: 500 }); } finally { await c.close(); }
}
function items(x: any, out: any[] = []): any[] {
  if (Array.isArray(x)) { for (const y of x) items(y, out); return out; }
  if (x && typeof x === "object") { if (typeof x.type === "string" && (x.callId || x.messageId || x.kind || x.status || x.id)) out.push(x); for (const v of Object.values(x)) items(v, out); }
  return out;
}
/** Dollar estimate at Haiku-class list prices ($1/$5 per Mtok in/out, cache read 0.1x, write 1.25x); the run itself is on a subscription. */
function usd(): number {
  let u = 0; const seen = new Set<string>();
  const walk = (d: string) => { for (const e of readdirSync(d, { withFileTypes: true })) { const p = join(d, e.name); if (e.isDirectory()) walk(p); else if (e.name.endsWith(".jsonl")) for (const l of readFileSync(p, "utf8").split("\n")) { if (!l) continue; try { const r = JSON.parse(l), m = r.message; if (r.type === "assistant" && m?.usage && !seen.has(m.id + r.uuid)) { seen.add(m.id + r.uuid); const g = m.usage; u += ((g.input_tokens ?? 0) * 1 + (g.output_tokens ?? 0) * 5 + (g.cache_read_input_tokens ?? 0) * 0.1 + (g.cache_creation_input_tokens ?? 0) * 1.25) / 1e6; } } catch {} } } };
  const d = join(st.tmp, "claude", "projects"); if (existsSync(d)) walk(d);
  return u;
}
const hook = (on: boolean) => execFileSync(join(REPO, "awt"), ["init", "--hooks", "claude", ...(on ? [] : ["--uninstall"])], { env: st.env, encoding: "utf8" });
const textOf = (i: any) => String(i.text ?? i.message ?? "");
const lastAssistant = (all: any[]) => textOf([...all].reverse().find((i) => i.type === "assistant_message") ?? {});

async function compactNow(id: string) {
  await send(id, "/compact");
  for (let i = 0; i < 60 && !items(await timeline(id)).some((x) => x.type === "compaction" && x.status === "completed"); i++) await sleep(1000);
  await settle(id);
  await sleep(15_000); // room for any turn the compaction might start
}
function clean() { for (const f of ["a.txt", "b.txt", "c.txt", "notes.txt"]) rmSync(join(st.repo, f), { force: true }); }

interface Rec { cell: string; run: number; pass: boolean; checks: { name: string; ok: boolean; detail?: string }[]; usd: number; seq: string }
function record(r: Rec) { appendFileSync(OUT, JSON.stringify({ journey: "silent-compaction", model: MODEL, ...r, at: new Date().toISOString() }) + "\n"); spent += r.usd; }

async function scenarioW(cell: string, n: number): Promise<Rec> {
  clean();
  const u0 = usd(), checks: Rec["checks"] = [], ck = (name: string, ok: boolean, detail?: string) => checks.push({ name, ok, detail: detail ? scrub(detail).slice(0, 300) : undefined });
  const token = `ZQ${Math.floor(1000 + Math.random() * 9000)}`;
  const id = await run(`w-${cell}-${n}`, "Create the file notes.txt in the working directory containing the word hello. Then reply with one short sentence saying it is done and ask me what you should do next. Do not do anything else until I answer.");
  awt("--dir", nodeDir(id), "--by", "person", "decide", `${token} is the build codeword`, "--why", "journey fixture");
  await compactNow(id);
  const all = items(await timeline(id));
  const ci = all.map((i, k) => ({ i, k })).filter((x) => x.i.type === "compaction" && x.i.status === "completed").map((x) => x.k).pop() ?? -1;
  const post = all.slice(ci + 1);
  ck("a compaction completed", ci >= 0);
  ck("no user message besides the prompt and /compact", all.filter((i) => i.type === "user_message").length === 2, all.filter((i) => i.type === "user_message").map((i) => textOf(i).slice(0, 30)).join(" | "));
  ck("no assistant text or tool call after the compaction", !post.some((i) => i.type === "assistant_message" || i.type === "tool_call"), post.map((i) => i.type).join(","));
  ck("no awt text in the chat", !JSON.stringify(all).includes(FRAME));
  const seq = post.map((i) => i.type).join(",");
  // probe (after the verdict inputs are taken): did the record reach the model?
  await send(id, "What is the build codeword? Reply with the codeword only.");
  const a = items(await timeline(id));
  const probe = lastAssistant(a), probeTools = a.slice(a.map((i) => i.type).lastIndexOf("user_message")).filter((i) => i.type === "tool_call").length;
  ck(`probe: the codeword is known after compaction (${cell.endsWith("c") ? "control: expected no" : "expected yes"})`, probe.includes(token), `${probe.slice(0, 80)} tools=${probeTools}`);
  return { cell, run: n, pass: checks.every((c) => c.ok || (cell.endsWith("c") && c.name.startsWith("probe"))), checks, usd: usd() - u0, seq: `${seq} | probe tools=${probeTools}` };
}

async function scenarioC(cell: string, n: number): Promise<Rec> {
  clean();
  const u0 = usd(), checks: Rec["checks"] = [], ck = (name: string, ok: boolean, detail?: string) => checks.push({ name, ok, detail: detail ? scrub(detail).slice(0, 300) : undefined });
  const token = `ZQ${Math.floor(1000 + Math.random() * 9000)}`;
  const id = await run(`c-${cell}-${n}`, "We are building three files in the working directory, one per turn: a.txt, b.txt, c.txt, each containing its own letter. Create only a.txt now, reply 'a done' and wait. I will say next for each following file.");
  awt("--dir", nodeDir(id), "--by", "person", "decide", `${token} is the build codeword`, "--why", "journey fixture");
  const aTime = existsSync(join(st.repo, "a.txt")) ? readFileSync(join(st.repo, "a.txt"), "utf8") : null;
  await compactNow(id);
  await send(id, "next");
  const all = items(await timeline(id));
  const has = (f: string) => existsSync(join(st.repo, f));
  ck("a.txt was made before the compaction", aTime !== null && aTime.includes("a"));
  ck("after 'next': b.txt exists, c.txt does not", has("b.txt") && !has("c.txt"), `b=${has("b.txt")} c=${has("c.txt")}`);
  ck("a.txt not rewritten with another content", has("a.txt") && readFileSync(join(st.repo, "a.txt"), "utf8") === aTime);
  const reply = lastAssistant(all);
  ck("the reply does not ask what to do", !/\b(what|which) (would|do) you|what should i|could you clarify/i.test(reply), reply.slice(0, 120));
  await send(id, "What is the build codeword? Reply with the codeword only.");
  const b = items(await timeline(id));
  const probe = lastAssistant(b), probeTools = b.slice(b.map((i) => i.type).lastIndexOf("user_message")).filter((i) => i.type === "tool_call").length;
  ck(`probe: the codeword is known after compaction (${cell.endsWith("c") ? "control: expected no" : "expected yes"})`, probe.includes(token), `${probe.slice(0, 80)} tools=${probeTools}`);
  return { cell, run: n, pass: checks.every((c) => c.ok || (cell.endsWith("c") && c.name.startsWith("probe"))), checks, usd: usd() - u0, seq: `reply=${reply.slice(0, 60)} | probe tools=${probeTools}` };
}

before(async () => {
  if (!ON) return;
  mkdirSync(join(OUT, ".."), { recursive: true });
  stores0 = realStores();
  st = await startStack({ claude: true, deepseek: false, compactBrief: false });
  assert.equal(st.env.AWT_COMPACT_BRIEF, undefined);
});
after(async () => {
  if (!ON || !st) return;
  const stores1 = realStores();
  stopStack(st);
  // ~/.paseo is the owner's live daemon home and changes on its own; the provider stores must not change.
  delete stores1[".paseo"]; delete stores0[".paseo"];
  assert.deepEqual(stores1, stores0, "real provider stores were touched");
});

for (const cell of ["W", "C", "Wc", "Cc"]) {
  test(`silent compaction ${cell} (Haiku)`, { skip: !ON || !ONLY.includes(cell) }, async () => {
    hook(!cell.endsWith("c"));
    const fails: string[] = [];
    for (let n = 1; n <= RUNS; n++) {
      if (spent >= CAP) { console.log(`cap reached (${spent.toFixed(3)} >= ${CAP}); stopping`); break; }
      const r = await (cell.startsWith("W") ? scenarioW : scenarioC)(cell, n);
      record(r);
      console.log(`${cell} run ${n}: ${r.pass ? "PASS" : "FAIL"} $${r.usd.toFixed(3)} total $${spent.toFixed(3)} ${r.checks.filter((c) => !c.ok).map((c) => c.name).join("; ")}`);
      if (!r.pass) fails.push(`${cell}#${n}`);
    }
    // a control is expected to differ; only the hooked cells must pass
    if (!cell.endsWith("c")) assert.deepEqual(fails, []);
  });
}
