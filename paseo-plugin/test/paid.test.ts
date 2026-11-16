// Paid provider journeys E-P8..E-P17 of tests/TEST-SPEC.md. Real Claude Code, opencode and pi in an isolated Paseo daemon.
// Gated: AWT_E2E_PAID=1 (owner approval required; spends tokens). Select with AWT_PAID_ONLY="E-P8,E-P11" (default: all).
// Never touches ~/.paseo, ~/.local/share/awt or the real provider stores. Results: $AWT_PAID_OUT (default /tmp/awt-logs/paid-results.jsonl).
import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { execFile, execFileSync } from "node:child_process";
import { appendFileSync, existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import { createPaseoClient } from "@getpaseo/client";
import { COMPACTED_MARK } from "../server/prompt.js";
import { RECEIPT_KIND } from "../shared/receipt.js";
import { type Stack, paseo, realStores, scrub, startStack, stopStack } from "./paid-env.js";

const ON = process.env.AWT_E2E_PAID === "1";
const ONLY = (process.env.AWT_PAID_ONLY ?? "").split(",").map((x) => x.trim()).filter(Boolean);
const OUT = process.env.AWT_PAID_OUT ?? "/tmp/awt-logs/paid-results.jsonl";
const RUNS = Number(process.env.AWT_PAID_RUNS ?? "5");
const want = (id: string) => ON && (ONLY.length === 0 || ONLY.includes(id));
const MODEL = { claude: "claude-haiku-5-5", opencode: "deepseek/deepseek-flash", pi: "deepseek/deepseek-flash" } as const;
type Prov = keyof typeof MODEL;
const pexec = promisify(execFile);

let st: Stack;
let before_stores: Record<string, string> = {};
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const px = (...a: string[]) => paseo(st, ...a);
const awt = (dir: string, ...a: string[]) => execFileSync(join(st.env.AWT_BIN!, ""), ["--dir", dir, ...a], { env: st.env, encoding: "utf8" });
const agents = (): any[] => JSON.parse(px("ls", "-a", "--json"));
const idOf = (title: string) => agents().find((a) => a.name === title)?.id as string;
const nodes = (): any[] => JSON.parse(awt(st.root, "list", "nodes", "--all", "--json"));
const nodeDir = (id: string) => { const n = nodes().find((x) => x.key === `paseo:agent/${id}`); return n ? join(st.root, n.path) : ""; };
const hooks = (): any[] => (existsSync(st.hookLog) ? readFileSync(st.hookLog, "utf8").trim().split("\n").filter(Boolean).map((l) => JSON.parse(l)) : []);
const argv = (): any[] => (existsSync(st.argvLog) ? readFileSync(st.argvLog, "utf8").trim().split("\n").filter(Boolean).map((l) => JSON.parse(l)) : []);
const hookAgent = (h: any) => h.payload?.agent?.id ?? h.payload?.agentId ?? null;

async function run(prov: Prov, title: string, prompt: string, extra: string[] = []): Promise<string> {
  try {
    await pexec("paseo", ["--home", st.home, "run", "--provider", prov, "--model", MODEL[prov], "--workspace", st.wsId, "--title", title, ...extra, prompt], { env: st.env, timeout: 300_000, encoding: "utf8" });
  } catch (e: any) { /* a timeout or a failed turn is judged from the files below */ if (!idOf(title)) throw new Error(scrub(`run ${title}: ${String(e.stderr ?? e.message).slice(0, 300)}`)); }
  await settle(idOf(title));
  return idOf(title);
}
/** Permission requests the harness had to answer so a journey could continue (each is a finding: the plugin did not pre-answer it). */
const answered: { agent: string; name: string; description: string }[] = [];
/** `paseo run` and `paseo send` return while a permission is pending. Allow each once, record it, and wait for idle. */
async function settle(id: string) {
  for (let i = 0; i < 12; i++) {
    let pend: any[] = [];
    try { pend = JSON.parse(px("permit", "ls", "--json") || "[]").filter((p: any) => p.agentId === id); } catch {}
    if (pend.length === 0) { try { await pexec("paseo", ["--home", st.home, "wait", id, "--timeout", "120"], { env: st.env, timeout: 150_000 }); } catch {} if (!JSON.parse(px("permit", "ls", "--json") || "[]").some((p: any) => p.agentId === id)) return; continue; }
    for (const p of pend) { answered.push({ agent: id, name: p.name, description: String(p.description ?? "") }); try { px("permit", "allow", id, p.id); } catch {} }
  }
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
const receiptsOf = (tl: any) => items(tl).filter((i) => i.type === "plugin" && i.kind === RECEIPT_KIND);
const toolCalls = (tl: any) => items(tl).filter((i) => i.type === "tool_call");

// Provider store readers (tokens and cost). Claude has no marginal cost on a subscription; its dollar figure is an estimate at Haiku-class list prices.
export interface Usage { input: number; output: number; cacheRead: number; cacheWrite: number; usd: number; note: string }
function claudeUsage(): Usage {
  const u: Usage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, usd: 0, note: "estimate at $1/$5 per Mtok in/out, cache read 0.1x, write 1.25x; the run is on a subscription" };
  const seen = new Set<string>();
  const walk = (d: string) => { for (const e of readdirSync(d, { withFileTypes: true })) { const p = join(d, e.name); if (e.isDirectory()) walk(p); else if (e.name.endsWith(".jsonl")) for (const l of readFileSync(p, "utf8").split("\n")) { if (!l) continue; try { const r = JSON.parse(l); const m = r.message; if (r.type === "assistant" && m?.usage && !seen.has(m.id + r.uuid)) { seen.add(m.id + r.uuid); u.input += m.usage.input_tokens ?? 0; u.output += m.usage.output_tokens ?? 0; u.cacheRead += m.usage.cache_read_input_tokens ?? 0; u.cacheWrite += m.usage.cache_creation_input_tokens ?? 0; } } catch {} } } };
  const d = join(st.tmp, "claude", "projects"); if (existsSync(d)) walk(d);
  u.usd = (u.input * 1 + u.output * 5 + u.cacheRead * 0.1 + u.cacheWrite * 1.25) / 1e6;
  return u;
}
function sql(q: string): string { const db = join(st.tmp, "xdg", "data", "opencode", "opencode.db"); return existsSync(db) ? execFileSync("sqlite3", ["-readonly", db, q], { encoding: "utf8" }).trim() : ""; }
function opencodeUsage(): Usage {
  const r = sql("select coalesce(sum(json_extract(data,'$.tokens.input')),0), coalesce(sum(json_extract(data,'$.tokens.output')),0), coalesce(sum(json_extract(data,'$.tokens.cache.read')),0), coalesce(sum(json_extract(data,'$.tokens.cache.write')),0), coalesce(sum(json_extract(data,'$.cost')),0) from message where json_extract(data,'$.role')='assistant'").split("|").map(Number);
  return { input: r[0] || 0, output: r[1] || 0, cacheRead: r[2] || 0, cacheWrite: r[3] || 0, usd: r[4] || 0, note: "opencode's own cost field" };
}
function piUsage(): Usage {
  const u: Usage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, usd: 0, note: "pi's own cost field" };
  const walk = (d: string) => { for (const e of readdirSync(d, { withFileTypes: true })) { const p = join(d, e.name); if (e.isDirectory()) walk(p); else if (e.name.endsWith(".jsonl")) for (const l of readFileSync(p, "utf8").split("\n")) { if (!l) continue; try { const m = JSON.parse(l).message; if (m?.role === "assistant" && m.usage) { u.input += m.usage.input ?? 0; u.output += m.usage.output ?? 0; u.cacheRead += m.usage.cacheRead ?? 0; u.cacheWrite += m.usage.cacheWrite ?? 0; u.usd += m.usage.cost?.total ?? 0; } } catch {} } } };
  const d = join(st.tmp, "pi", "sessions"); if (existsSync(d)) walk(d);
  return u;
}
const usageOf = (p: Prov): Usage => ({ claude: claudeUsage, opencode: opencodeUsage, pi: piUsage })[p]();
const diff = (a: Usage, b: Usage): Usage => ({ input: b.input - a.input, output: b.output - a.output, cacheRead: b.cacheRead - a.cacheRead, cacheWrite: b.cacheWrite - a.cacheWrite, usd: b.usd - a.usd, note: b.note });

/** The persistence record Paseo wrote for an agent (sessionId, nativeHandle). */
function persistence(id: string): any {
  const walk = (d: string): string => { if (!existsSync(d)) return ""; for (const e of readdirSync(d, { withFileTypes: true })) { const p = join(d, e.name); if (e.isDirectory()) { const r = walk(p); if (r) return r; } else if (e.name === `${id}.json`) return p; } return ""; };
  const f = walk(join(st.home, "agents"));
  return f ? JSON.parse(readFileSync(f, "utf8")).persistence ?? {} : {};
}

interface Check { name: string; ok: boolean; detail?: string }
class Journey {
  checks: Check[] = []; notes: string[] = []; usage: Usage | null = null;
  private u0: Usage | null = null;
  constructor(readonly id: string, readonly prov: Prov, readonly title: string) { this.u0 = usageOf(prov); }
  check(name: string, ok: boolean, detail?: string) { this.checks.push({ name, ok, detail: detail ? scrub(detail).slice(0, 400) : undefined }); }
  note(s: string) { this.notes.push(scrub(s).slice(0, 600)); }
  finish(status?: "PASS" | "FAIL" | "SKIP") {
    this.usage = diff(this.u0!, usageOf(this.prov));
    const st_ = status ?? (this.checks.every((c) => c.ok) ? "PASS" : "FAIL");
    appendFileSync(OUT, JSON.stringify({ journey: this.id, title: this.title, provider: this.prov, model: MODEL[this.prov], status: st_, checks: this.checks, notes: this.notes, usage: this.usage, at: new Date().toISOString() }) + "\n");
    if (st_ === "FAIL") assert.fail(this.checks.filter((c) => !c.ok).map((c) => `${c.name}${c.detail ? ` (${c.detail})` : ""}`).join("; "));
  }
}

/** The common E-P8/E-P11/E-P14 probe. */
async function envProbe(j: Journey, prov: Prov, title: string, resumeFirst: string, extra: string[] = []) {
  const h0 = hooks().length, a0 = argv().length;
  const id = await run(prov, title, `${resumeFirst} Then run the shell command: awt note "${prov} probe". Then write the file $AWT_DIR/scratch/plan.md with one line, using your file-writing tool, not the shell. Reply DONE.`, extra);
  j.check("agent exists", !!id);
  const dir = nodeDir(id);
  for (let i = 0; i < 20 && !hooks().slice(h0).some((h) => h.hook === "agent.turn.after" && hookAgent(h) === id); i++) await sleep(500);
  const hs = hooks().slice(h0);
  const mine = hs.filter((h) => hookAgent(h) === id);
  const names = (n: string) => hs.filter((h) => h.hook === n);
  j.check("H5 create.before for provider", names("agent.create.before").some((h) => h.payload?.config?.provider === prov));
  j.check("H5 open.before", mine.some((h) => h.hook === "agent.open.before"));
  j.check("H5 one turn.before/turn.after pair", mine.filter((h) => h.hook === "agent.turn.before").length === 1 && mine.filter((h) => h.hook === "agent.turn.after").length === 1, `before=${mine.filter((h) => h.hook === "agent.turn.before").length} after=${mine.filter((h) => h.hook === "agent.turn.after").length}`);
  j.check("H5 provider field", mine.filter((h) => h.payload?.agent).every((h) => h.payload.agent.provider === prov));
  const turn = mine.find((h) => h.hook === "agent.turn.after");
  j.note(`turn outcome ${JSON.stringify(turn?.payload?.outcome)}`);
  const tl = await timeline(id);
  const calls = toolCalls(tl);
  const resume = calls.find((c) => /awt_resume/.test(c.name));
  if (prov === "pi") j.note(`awt_resume tool call ${resume ? "present" : "absent (fell back to: " + (argv().slice(a0).some((x) => x.argv[0] === "resume") ? "awt resume" : "nothing") + ")"}`);
  else if (prov === "opencode" && !resume) j.note("FINDING: opencode was never offered awt_resume. Paseo 0.15.4 gives opencode's bridge plugin a static tool manifest without plugin tools (agent tools are bound per session only for MCP). The agent fell back to BRIEF.md or awt resume.");
  else j.check("tool call awt_resume completed without error", !!resume && resume.status === "completed" && !resume.error, JSON.stringify(resume ?? null).slice(0, 200));
  const mineArgv = argv().slice(a0).filter((x) => x.AWT_BY === id);
  const note = mineArgv.find((x) => x.argv[0] === "note");
  j.check("argv: note ran with AWT_DIR = agent node and AWT_BY = agent id", !!note && note.AWT_DIR === dir && note.AWT_BY === id, JSON.stringify(note ?? null).slice(0, 300));
  j.check("plan.md in the node", existsSync(join(dir, "scratch", "plan.md")));
  const perms = mine.filter((h) => h.hook === "agent.permission.before");
  for (const p of perms) j.note(`permission.before: name=${p.payload.request.name} kind=${p.payload.request.kind} title=${p.payload.request.title} desc=${String(p.payload.request.description ?? "").replace(st.tmp, "$T").slice(0, 160)}`);
  const wrote = perms.filter((p) => /plan\.md|scratch/.test(JSON.stringify(p.payload.request)));
  j.note(`permission requests for the plan.md write: ${wrote.length}${wrote.length ? " (answered by the plugin? see pending check)" : ""}`);
  const harnessAnswered = answered.filter((p) => p.agent === id);
  // A pending Bash(awt ...) is a finding (unverified fact 1), not a failure: shell requests are the person's to answer. The plugin's own
  // tool and the node write must never wait for a person.
  const blocking = harnessAnswered.filter((p) => /awt_resume/.test(p.name) || /plan\.md|scratch/.test(`${p.name} ${p.description}`));
  j.check("no permission for awt_resume or the plan.md write needed the harness to answer", blocking.length === 0, JSON.stringify(blocking.map((p) => p.name)));
  for (const p of harnessAnswered) j.note(`FINDING: harness had to allow a pending permission: ${p.name}`);
  const bashAwt = perms.filter((p) => /awt/.test(JSON.stringify(p.payload.request.input ?? "")) && /bash|shell/i.test(p.payload.request.name + p.payload.request.kind));
  if (bashAwt.length) j.note(`FINDING (unverified fact 1): ${bashAwt.length} permission request(s) for Bash(awt ...)`);
  // The receipt is appended after the plugin's own awt calls, a moment after turn.after is logged.
  let rc = receiptsOf(tl);
  for (let i = 0; i < 15 && rc.length === 0; i++) { await sleep(1000); rc = receiptsOf(await timeline(id)); }
  j.check("exactly 1 receipt with counts.note == 1", rc.length === 1 && rc[0].data?.counts?.note === 1, JSON.stringify(rc.map((r) => r.data?.counts)));
  return { id, dir, tl };
}

before(async () => {
  if (!ON) return;
  before_stores = realStores();
  const need = (ids: string[]) => ids.some((i) => want(i));
  st = await startStack({ claude: need(["E-P8", "E-P9", "E-P10", "E-P17"]), deepseek: need(["E-P11", "E-P12", "E-P13", "E-P14", "E-P15", "E-P16"]) });
  appendFileSync(OUT, JSON.stringify({ journey: "_setup", paseo: px("--version").trim(), claude: execFileSync("claude", ["--version"], { encoding: "utf8" }).trim(), opencode: execFileSync("opencode", ["--version"], { encoding: "utf8" }).trim(), pi: execFileSync("pi", ["--version"], { encoding: "utf8", env: st.env }).trim(), at: new Date().toISOString() }) + "\n");
});
after(() => {
  if (!ON || !st) return;
  // U3 leak check: nothing of ours in the real stores.
  const leaks: string[] = [];
  const h = homedir(), marker = st.tmp.split("/").pop()!;
  const grep = (p: string) => { try { return execFileSync("grep", ["-rl", "--", marker, p], { encoding: "utf8", timeout: 60_000 }).trim(); } catch { return ""; } };
  for (const p of [".paseo/agents", ".claude/projects", ".pi/agent/sessions"]) if (existsSync(join(h, p)) && grep(join(h, p))) leaks.push(p);
  try { const n = execFileSync("sqlite3", ["-readonly", join(h, ".local/share/opencode/opencode.db"), `select count(*) from session where directory like '%${marker}%'`], { encoding: "utf8" }).trim(); if (n !== "0") leaks.push("opencode.db"); } catch {}
  appendFileSync(OUT, JSON.stringify({ journey: "_postflight", leaks, coarseStoreChanged: Object.keys(before_stores).filter((k) => realStores()[k] !== before_stores[k]), at: new Date().toISOString() }) + "\n");
  stopStack(st, process.env.AWT_PAID_KEEP === "1");
});

test("E-P8 Claude Code: env, tool, permissions, receipts", { skip: !want("E-P8") }, async () => {
  const j = new Journey("E-P8", "claude", "cc1");
  await envProbe(j, "claude", "cc1", "Call the awt_resume tool.");
  j.finish();
});

test("E-P8b Claude Code in mode auto: the same probe with --mode auto", { skip: !want("E-P8") && !want("E-P8b") }, async () => {
  const j = new Journey("E-P8b", "claude", "cc1b");
  await envProbe(j, "claude", "cc1b", "Call the awt_resume tool.", ["--mode", "auto"]);
  j.finish();
});

test("E-P9 Claude Code: native subagent", { skip: !want("E-P9") }, async () => {
  const j = new Journey("E-P9", "claude", "cc2");
  const c0 = hooks().filter((h) => h.hook === "agent.create.after").length, a0 = argv().length;
  const id = await run("claude", "cc2", 'Use the Task tool to start a subagent that runs: awt note "from the subagent". Then run: awt note "from the parent". Reply DONE.');
  const created = hooks().filter((h) => h.hook === "agent.create.after").length - c0;
  j.check("no agent.create.* for the subagent", created === 1, `agent.create.after count ${created}`);
  const tl = await timeline(id);
  j.check("timeline has a sub_agent item", /"sub_agent"/.test(JSON.stringify(tl)));
  const notes = argv().slice(a0).filter((x) => x.argv[0] === "note");
  j.check("argv shows both notes", notes.some((x) => /subagent/.test(x.argv[1])) && notes.some((x) => /parent/.test(x.argv[1])), JSON.stringify(notes.map((x) => x.argv[1])));
  const dir = nodeDir(id);
  for (const n of notes) j.note(`note "${n.argv[1]}" ran with AWT_DIR ${n.AWT_DIR === dir ? "= parent's node" : "!= parent's node: " + String(n.AWT_DIR).replace(st.tmp, "$T")} AWT_BY ${n.AWT_BY === id ? "= parent" : n.AWT_BY}`);
  const sid = persistence(id).sessionId;
  const sub = sid ? findFiles(join(st.tmp, "claude", "projects"), (p) => p.includes(`/${sid}/subagents/agent-`) && p.endsWith(".jsonl")) : [];
  j.check("subagent transcript exists with isSidechain true", sub.length > 0 && readFileSync(sub[0], "utf8").split("\n").filter(Boolean).some((l) => JSON.parse(l).isSidechain === true), `sessionId=${sid} files=${sub.length}`);
  j.finish();
});

function findFiles(root: string, pred: (p: string) => boolean, out: string[] = []): string[] {
  if (!existsSync(root)) return out;
  for (const e of readdirSync(root, { withFileTypes: true })) { const p = join(root, e.name); if (e.isDirectory()) findFiles(p, pred, out); else if (pred(p)) out.push(p); }
  return out;
}

/** One compaction run; returns what was observed. */
async function compactRun(prov: Prov, title: string, compactCmd: string) {
  const a0 = argv().length;
  const id = await run(prov, title, 'Run the shell command: awt note "before compact". Then reply DONE.');
  await send(id, compactCmd);
  // The plugin sends the brief back when the compacting turn ends; let that turn finish before the next prompt.
  for (let i = 0; i < 30 && !JSON.stringify(await timeline(id)).includes(COMPACTED_MARK); i++) await sleep(1000);
  await settle(id);
  const mark = argv().length;
  const t1 = Date.now();
  await send(id, "Continue the parsekit task. First re-read your task brief, then write one more note about what you remember.");
  // pi's /compact runs outside any turn, so its brief is sent when the next turn ends, a moment after the harness sees the turn end.
  for (let i = 0; i < 30 && !JSON.stringify(await timeline(id)).includes(COMPACTED_MARK); i++) await sleep(1000);
  await settle(id);
  const tl = await timeline(id);
  const comp = items(tl).filter((i) => i.type === "compaction");
  const post = argv().slice(mark).filter((x) => x.AWT_BY === id);
  const WRITES = new Set(["note", "state", "decide", "ask", "answer", "ref", "init"]);
  const firstWrite = post.findIndex((x) => WRITES.has(x.argv[0]));
  const resumeIdx = post.findIndex((x) => x.argv[0] === "resume");
  const all = items(tl);
  const ci = all.findIndex((i) => i.type === "compaction");
  const resumeTool = all.slice(ci < 0 ? all.length : ci).filter((i) => i.type === "tool_call" && /awt_resume/.test(i.name));
  // The brief is back when a resume (tool or command) happens after compaction and before any awt write.
  const afterCompaction = all.slice(ci < 0 ? all.length : ci);
  const sentBack = afterCompaction.some((i) => i.type === "user_message" && String(i.text ?? "").startsWith(COMPACTED_MARK));
  const brief = sentBack || (resumeTool.length > 0 ? firstWrite < 0 || resumeIdx < 0 || resumeIdx < firstWrite : resumeIdx >= 0 && (firstWrite < 0 || resumeIdx < firstWrite));
  const errs = [...JSON.stringify(tl).matchAll(/\[Error\][^"]{0,160}/g)].map((m) => m[0]);
  return { id, tl, comp, brief, sentBack, errs, post, t1, resumeTool: resumeTool.length, receipts: receiptsOf(tl) };
}

test("E-P10 Claude Code: compaction and transcript", { skip: !want("E-P10") }, async () => {
  const j = new Journey("E-P10", "claude", "cc3");
  const runs = await Promise.all(Array.from({ length: RUNS }, (_, i) => compactRun("claude", `cc3-${i}`, "/compact")));
  const withComp = runs.filter((r) => r.comp.some((c) => c.status === "completed"));
  j.check("a compaction item with status completed (every run)", withComp.length === RUNS, `${withComp.length}/${RUNS}`);
  const ok = runs.filter((r) => r.brief).length;
  j.check(`brief returns after compaction in at least ${Math.ceil(RUNS * 0.8)} of ${RUNS} runs`, ok >= Math.ceil(RUNS * 0.8), `${ok}/${RUNS}`);
  const rows = findFiles(join(st.tmp, "claude", "projects"), (p) => p.endsWith(".jsonl") && !p.includes("/subagents/")).flatMap((f) => readFileSync(f, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l)));
  j.check("transcripts have system/compact_boundary rows", rows.some((r) => r.type === "system" && (r.subtype === "compact_boundary")), `rows=${rows.length}`);
  j.check("transcripts have isCompactSummary rows", rows.some((r) => r.isCompactSummary === true));
  j.check("no transcript row contains the receipt kind", !rows.some((r) => /awt[.-]receipt/.test(JSON.stringify(r))));
  j.note(`per run: ${runs.map((r) => `${r.id.slice(0, 6)} comp=${r.comp.map((c) => c.status).join("/")} resumeTool=${r.resumeTool} sentBack=${r.sentBack} errors=${JSON.stringify(r.errs)} post=${r.post.map((x) => x.argv[0]).join(",")}`).join(" | ")}`);
  j.finish();
});

test("E-P11 opencode: env, tool, permissions, receipts", { skip: !want("E-P11") }, async () => {
  const j = new Journey("E-P11", "opencode", "oc1");
  const serves = () => { try { return execFileSync("sh", ["-c", `ps -axeww -o command | grep '[o]pencode serve' | grep -c 'XDG_DATA_HOME=${st.tmp}' || true`], { encoding: "utf8" }).trim(); } catch { return "?"; } };
  const before = serves();
  await envProbe(j, "opencode", "oc1", "Call the awt_resume tool.");
  const extra = await Promise.all(["oc1b", "oc1c"].map((t) => run("opencode", t, "Reply with the single word OK.")));
  const after_ = serves();
  const n = Number(after_);
  j.note(`opencode serve processes with $T in argv: before=${before} after 3 agents=${after_}; opencode ${execFileSync("opencode", ["--version"], { encoding: "utf8" }).trim()}`);
  j.check("serve count <= agents + 1", n <= 4, `after=${after_}`);
  const perm = hooks().find((h) => h.hook === "agent.permission.before" && h.payload.agent.provider === "opencode");
  j.note(`permission request shape: ${perm ? JSON.stringify({ name: perm.payload.request.name, kind: perm.payload.request.kind, keys: Object.keys(perm.payload.request), inputKeys: Object.keys(perm.payload.request.input ?? {}) }) : "none seen"}`);
  void extra;
  j.finish();
});

test("E-P12 opencode: child session", { skip: !want("E-P12") }, async () => {
  const j = new Journey("E-P12", "opencode", "oc2");
  const c0 = hooks().filter((h) => h.hook === "agent.create.after").length, a0 = argv().length;
  const id = await run("opencode", "oc2", 'Use the task tool to have a subagent run: awt note "from the child". Wait for it, then reply DONE.');
  j.check("no agent.create.* for the child", hooks().filter((h) => h.hook === "agent.create.after").length - c0 === 1);
  const tl = await timeline(id);
  j.check("timeline has a sub_agent item", /"sub_agent"/.test(JSON.stringify(tl)));
  const sid = persistence(id).sessionId;
  const kids = sid ? sql(`select id from session where parent_id='${sid}'`) : "";
  j.check("opencode.db has a session whose parent_id is the agent's sessionId", kids.length > 0, `sessionId=${sid}`);
  const notes = argv().slice(a0).filter((x) => x.argv[0] === "note");
  j.check("the child's note ran", notes.length > 0);
  j.note(`child note landed in ${notes.map((n) => (n.AWT_DIR === nodeDir(id) ? "the agent's node" : String(n.AWT_DIR).replace(st.tmp, "$T")) + " by " + (n.AWT_BY === id ? "agent" : n.AWT_BY)).join("; ")}`);
  const cp = hooks().filter((h) => h.hook === "agent.permission.before" && hookAgent(h) === id);
  j.note(`permission requests attributed to the parent during the child's work: ${cp.length}`);
  j.finish();
});

test("E-P13 opencode: compaction and transcript", { skip: !want("E-P13") }, async () => {
  const j = new Journey("E-P13", "opencode", "oc3");
  const runs = await Promise.all(Array.from({ length: RUNS }, (_, i) => compactRun("opencode", `oc3-${i}`, "/compact")));
  j.check("a compaction timeline item (every run)", runs.filter((r) => r.comp.length > 0).length === RUNS, `${runs.filter((r) => r.comp.length > 0).length}/${RUNS}`);
  j.check("a part with data.type = compaction", Number(sql("select count(*) from part where json_extract(data,'$.type')='compaction'")) >= RUNS);
  j.note(`session.time_compacting set on ${sql("select count(*) from session where time_compacting is not null")} sessions (opencode 1.19.3 records a compaction part, not this column, for /compact)`);
  const ok = runs.filter((r) => r.brief).length;
  j.check(`brief returns in at least ${Math.ceil(RUNS * 0.8)} of ${RUNS} runs`, ok >= Math.ceil(RUNS * 0.8), `${ok}/${RUNS}`);
  j.note("system prompt after compaction: SKIP (opencode keeps no request log in 1.19.3 that the harness can read)");
  j.note(`per run: ${runs.map((r) => `${r.id.slice(0, 6)} comp=${r.comp.map((c) => c.status).join("/")} resumeTool=${r.resumeTool} sentBack=${r.sentBack} errors=${JSON.stringify(r.errs)} post=${r.post.map((x) => x.argv[0]).join(",")}`).join(" | ")}`);
  j.finish();
});

test("E-P14 pi: env, tool, permissions, receipts (arm A, no MCP adapter)", { skip: !want("E-P14") }, async () => {
  const j = new Journey("E-P14A", "pi", "pi1");
  await envProbe(j, "pi", "pi1", "Call the awt_resume tool if you have it, otherwise run: awt resume.");
  j.finish();
});

test("E-P14 pi: env, tool, permissions, receipts (arm B, pi-mcp-adapter)", { skip: !want("E-P14B") && !want("E-P14") }, async () => {
  const j = new Journey("E-P14B", "pi", "pi1b");
  try { execFileSync("pi", ["install", "npm:pi-mcp-adapter"], { env: st.env, encoding: "utf8", timeout: 240_000, stdio: "pipe" }); } catch (e: any) { j.note(`pi install pi-mcp-adapter failed: ${String(e.stderr ?? e.message).slice(0, 200)}`); j.finish("SKIP"); return; }
  await envProbe(j, "pi", "pi1b", "Call the awt_resume tool.");
  j.finish();
});

test("E-P15 pi: subagent", { skip: !want("E-P15") }, async () => {
  const j = new Journey("E-P15", "pi", "pi2");
  j.note("SKIP: no subagent extension is installed in the isolated pi home, and the spec makes this journey conditional on one");
  j.finish("SKIP");
});

test("E-P16 pi: compaction and transcript", { skip: !want("E-P16") }, async () => {
  const j = new Journey("E-P16", "pi", "pi3");
  const runs = await Promise.all(Array.from({ length: RUNS }, (_, i) => compactRun("pi", `pi3-${i}`, "/compact")));
  j.check("compaction timeline items (every run)", runs.filter((r) => r.comp.length > 0).length === RUNS, `${runs.filter((r) => r.comp.length > 0).length}/${RUNS}`);
  const files = findFiles(join(st.tmp, "pi", "sessions"), (p) => p.endsWith(".jsonl"));
  const rows = files.flatMap((f) => readFileSync(f, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l)));
  const comp = rows.filter((r) => r.type === "compaction");
  // pi refuses to compact a session that is too small ("Nothing to compact") but Paseo still shows the compaction items; then there is nothing to check in the files.
  const refused = runs.some((r) => r.errs.some((e) => /Nothing to compact|Already compacted/.test(e)));
  if (refused && comp.length === 0) j.note(`FINDING: pi refused /compact in a small session (${runs.flatMap((r) => r.errs)[0]}); no compaction entry could be written, so the session-file check is skipped`);
  else j.check("session files have compaction entries with firstKeptEntryId and tokensBefore", comp.length > 0 && comp.every((c) => c.firstKeptEntryId && c.tokensBefore !== undefined), `entries=${comp.length}`);
  const idsOk = runs.every((r) => { const p = persistence(r.id); const f = p.nativeHandle && existsSync(p.nativeHandle) ? p.nativeHandle : ""; if (!f) return false; const hd = JSON.parse(readFileSync(f, "utf8").split("\n")[0]); return hd.id === p.sessionId; });
  j.check("header id equals persistence.sessionId (every run)", idsOk);
  const ok = runs.filter((r) => r.brief).length;
  j.check(`brief returns in at least ${Math.ceil(RUNS * 0.8)} of ${RUNS} runs`, ok >= Math.ceil(RUNS * 0.8), `${ok}/${RUNS}`);
  j.note(`per run: ${runs.map((r) => `${r.id.slice(0, 6)} comp=${r.comp.map((c) => c.status).join("/")} resumeTool=${r.resumeTool} sentBack=${r.sentBack} errors=${JSON.stringify(r.errs)} post=${r.post.map((x) => x.argv[0]).join(",")}`).join(" | ")}`);
  j.finish();
});

/** The labels Paseo stored for an agent (`paseo ls` and `paseo inspect` do not print them). */
function labelsOf(id: string): Record<string, string> {
  const walk = (d: string): string => { if (!existsSync(d)) return ""; for (const e of readdirSync(d, { withFileTypes: true })) { const p = join(d, e.name); if (e.isDirectory()) { const r = walk(p); if (r) return r; } else if (e.name === `${id}.json`) return p; } return ""; };
  const f = walk(join(st.home, "agents"));
  return f ? JSON.parse(readFileSync(f, "utf8")).labels ?? {} : {};
}

test("E-P17 Paseo-level subagent started by a real agent", { skip: !want("E-P17") }, async () => {
  const j = new Journey("E-P17", "claude", "cc4");
  const id = await run("claude", "cc4", `Use the Paseo create_agent tool to start a subagent in this workspace (provider claude, model ${MODEL.claude}) that runs: awt note "kid via paseo". Wait for it to finish, then reply DONE.`);
  // The child is its own agent in default mode: its Bash(awt ...) request waits for a person (a finding, as in E-P8). Answer it, then wait for the child.
  let kid: any;
  for (let i = 0; i < 30 && !kid; i++) { kid = agents().find((a) => a.id !== id && labelsOf(a.id)["paseo.parent-agent-id"] === id); if (!kid) await sleep(1000); }
  j.check("a child agent exists with label paseo.parent-agent-id = cc4's id", !!kid, JSON.stringify(agents().map((a) => a.name)));
  if (kid) {
    await settle(kid.id);
    for (let i = 0; i < 20 && receiptsOf(await timeline(kid.id)).length === 0; i++) await sleep(1000);
    const pdir = nodeDir(id), kdir = nodeDir(kid.id);
    j.check("child's node sits under cc4's node", !!kdir && kdir.startsWith(join(pdir, "agents") + "/"), `${kdir.replace(st.tmp, "$T")}`);
    const kr = receiptsOf(await timeline(kid.id));
    j.check("child's receipt: counts.note == 1, counts.state == 0", kr.length >= 1 && kr[0].data.counts.note === 1 && (kr[0].data.counts.state ?? 0) === 0, JSON.stringify(kr.map((r) => r.data.counts)));
    j.note(`child permission requests the harness answered: ${answered.filter((p) => p.agent === kid.id).map((p) => p.name).join(",") || "none"}`);
  }
  j.finish();
});
