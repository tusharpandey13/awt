import assert from "node:assert/strict";
import { test, afterEach } from "node:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { agentPayload, exists, openReq, rig, type Rig } from "./harness.js";
import { AWT_BLOCK } from "../server/prompt.js";

const rigs: Rig[] = [];
const mk = (...a: Parameters<typeof rig>) => {
  const r = rig(...a);
  rigs.push(r);
  return r;
};
afterEach(() => rigs.splice(0).forEach((r) => r.cleanup()));
const WS = { wks_1: { name: "main", directory: "/tmp/parsekit", projectId: "prj_1" } };

test("P1 workspace.create.after builds workspace and main task with refs", async () => {
  const r = mk({}, WS);
  await r.call("workspace.create.after", { workspace: { id: "wks_1", projectId: "prj_1", cwd: "/tmp/parsekit", name: "main", archivedAt: null } });
  const n = r.nodes();
  const ws = n.find((x) => x.key === "paseo:workspace/wks_1")!;
  assert.equal(ws.kind, "workspace");
  assert.equal(ws.path, "workspaces/parsekit-main");
  assert.ok(n.find((x) => x.key === "paseo:task/wks_1/main"));
  const targets = JSON.parse(r.awt(join(r.root, ws.path), "list", "refs", "--json")).map((x: any) => x.target).sort();
  assert.deepEqual(targets, ["/tmp/parsekit", "paseo:project/prj_1", "paseo:workspace/wks_1"]);
  await r.call("workspace.create.after", { workspace: { id: "wks_1", projectId: "prj_1", cwd: "/tmp/parsekit", name: "main", archivedAt: null } });
  assert.equal(r.nodes().length, n.length);
});

test("P2 agent.create.before appends the static block once and touches nothing else", async () => {
  const r = mk();
  const config = { provider: "claude", cwd: "/x", systemPrompt: "be kind", model: "m" };
  const out = await r.call("agent.create.before", { request: { config, env: { A: "1" } } });
  assert.equal(out.config.systemPrompt, "be kind\n\n" + AWT_BLOCK);
  assert.ok(AWT_BLOCK.length <= 700, String(AWT_BLOCK.length));
  assert.deepEqual({ ...out.config, systemPrompt: undefined }, { ...config, systemPrompt: undefined });
  assert.deepEqual(out.env, { A: "1" });
  const again = await r.call("agent.create.before", { request: out });
  assert.equal(again.config.systemPrompt, out.config.systemPrompt);
  assert.ok(!AWT_BLOCK.includes("awt resume`:") && !/# awt task/.test(AWT_BLOCK), "no brief text in the prompt");
});

test("P3 two agents opened at once share one main task", async () => {
  const r = mk({}, WS);
  await Promise.all(["a1", "a2", "a3", "a4"].map((a) => r.call("agent.open.before", openReq(a))));
  const n = r.nodes();
  assert.equal(n.filter((x) => x.key === "paseo:task/wks_1/main").length, 1);
  assert.equal(n.filter((x) => x.kind === "agent").length, 4);
  assert.equal(n.filter((x) => x.kind === "workspace").length, 1);
});

test("P4/P5 agent.open.before: env, tool, idempotent on resume", async () => {
  const r = mk({}, WS);
  const first = await r.call("agent.open.before", openReq("agt_1"));
  assert.equal(first.env.KEEP, "1");
  assert.equal(first.env.AWT_BY, "agt_1");
  assert.ok(exists(join(first.env.AWT_DIR, ".awt", "events.jsonl")));
  assert.ok(first.env.AWT_DIR.startsWith(r.root + "/workspaces/parsekit-main/tasks/main/agents/"), first.env.AWT_DIR);
  assert.deepEqual(first.tools.map((t: any) => t.name), ["awt_resume"]);
  assert.deepEqual(first.mcpServers, {});
  const again = await r.call("agent.open.before", openReq("agt_1", { reason: "resume", tools: first.tools }));
  assert.equal(again.env.AWT_DIR, first.env.AWT_DIR);
  assert.equal(again.tools.length, 1);
  assert.equal(r.nodes().filter((x) => x.kind === "agent").length, 1);
});

test("P6 awt_resume returns this agent's brief only", async () => {
  const r = mk({}, WS);
  const open = await r.call("agent.open.before", openReq("agt_1"));
  const text = (await open.tools[0].execute({}, { agent: agentPayload("agt_1"), paseo: {}, signal: new AbortController().signal })).text;
  assert.match(text, /# awt task/);
  assert.match(text, /## Lineage/);
  assert.match(text, /workspace parsekit--main/);
  const other = await open.tools[0].execute({}, { agent: agentPayload("agt_nope"), paseo: {}, signal: new AbortController().signal });
  assert.equal(other.isError, true);
});

test("P4 a subagent whose parent is known lands under the parent's node", async () => {
  const r = mk({}, WS);
  const parent = await r.call("agent.open.before", openReq("agt_p"));
  await r.call("agent.create.after", { agent: agentPayload("agt_p") });
  await r.call("agent.create.after", { agent: agentPayload("agt_c", { parentAgentId: "agt_p" }) });
  const child = r.nodes().find((x) => x.key === "paseo:agent/agt_c")!;
  assert.ok((r.root + "/" + child.path).startsWith(parent.env.AWT_DIR + "/agents/"), child.path);
});

test("P4 a subagent opened before its parent is known gets a parent ref and a note", async () => {
  const r = mk({}, WS);
  const parent = await r.call("agent.open.before", openReq("agt_p"));
  const child = await r.call("agent.open.before", openReq("agt_c")); // open request carries no parent
  await r.call("agent.create.after", { agent: agentPayload("agt_c", { parentAgentId: "agt_p" }) });
  const notes = r.rows(child.env.AWT_DIR, "note").map((n) => n.text);
  assert.ok(notes.some((t) => t.includes("agt_p")), JSON.stringify(notes));
  assert.ok(r.rows(child.env.AWT_DIR, "ref").some((x) => x.kind === "node" && x.target === parent.env.AWT_DIR));
});

test("P7 turn.after nudges once for a completed turn with no handoff", async () => {
  const r = mk({}, WS);
  const open = await r.call("agent.open.before", openReq("agt_1"));
  const done = { kind: "completed" };
  await r.call("agent.turn.before", { agent: agentPayload("agt_1"), turnId: "t1" });
  await r.call("agent.turn.after", { agent: agentPayload("agt_1"), turnId: "t1", outcome: done, timeline: [] });
  assert.equal(r.sent.length, 1);
  assert.match(r.sent[0].text, /awt state/);
  // the turn that answers the nudge never triggers another
  await r.call("agent.turn.before", { agent: agentPayload("agt_1"), turnId: "t2" });
  await r.call("agent.turn.after", { agent: agentPayload("agt_1"), turnId: "t2", outcome: done, timeline: [] });
  assert.equal(r.sent.length, 1);
  // a handoff recorded during the turn means no nudge
  await r.call("agent.turn.before", { agent: agentPayload("agt_1"), turnId: "t3" });
  r.awt(open.env.AWT_DIR, "state", "--now", "did it", "--next", "ship");
  await r.call("agent.turn.after", { agent: agentPayload("agt_1"), turnId: "t3", outcome: done, timeline: [] });
  assert.equal(r.sent.length, 1);
});

test("P7 no nudge for failed, canceled, subagent or unknown turns", async () => {
  const r = mk({}, WS);
  await r.call("agent.open.before", openReq("agt_1"));
  for (const outcome of [{ kind: "failed", error: { message: "x" } }, { kind: "canceled", reason: "user" }]) {
    await r.call("agent.turn.before", { agent: agentPayload("agt_1"), turnId: "t" });
    await r.call("agent.turn.after", { agent: agentPayload("agt_1"), turnId: "t", outcome, timeline: [] });
  }
  const sub = agentPayload("agt_1", { parentAgentId: "agt_x" });
  await r.call("agent.turn.before", { agent: sub, turnId: "t" });
  await r.call("agent.turn.after", { agent: sub, turnId: "t", outcome: { kind: "completed" }, timeline: [] });
  await r.call("agent.turn.after", { agent: agentPayload("agt_1"), turnId: "t", outcome: { kind: "completed" }, timeline: [] }); // no turn.before seen
  assert.equal(r.sent.length, 0);
});

test("P8 the plugin registers no permission hook", () => {
  const r = mk();
  assert.deepEqual([...r.hooks.keys()].filter((k) => k.includes("permission")), []);
});

test("P9 archive hooks mark done, or paused when work is open", async () => {
  const r = mk({}, WS);
  const a = await r.call("agent.open.before", openReq("agt_1"));
  await r.call("agent.archive.after", { agent: agentPayload("agt_1"), archivedAt: "2026-01-01T00:00:00Z" });
  assert.equal(r.nodes().find((x) => x.key === "paseo:agent/agt_1")!.status, "done");
  const b = await r.call("agent.open.before", openReq("agt_2"));
  r.awt(b.env.AWT_DIR, "ask", "who owns this?");
  await r.call("agent.archive.after", { agent: agentPayload("agt_2"), archivedAt: "2026-01-01T00:00:00Z" });
  assert.equal(r.nodes().find((x) => x.key === "paseo:agent/agt_2")!.status, "paused");
  await r.call("workspace.archive.after", { workspace: { id: "wks_1", projectId: "prj_1", cwd: "/tmp/parsekit", name: "main", archivedAt: "x" } });
  const ws = r.nodes().find((x) => x.key === "paseo:workspace/wks_1")!;
  assert.ok(["done", "paused"].includes(ws.status));
  assert.ok(a.env.AWT_DIR);
});

test("P10 history opens are left alone", async () => {
  const r = mk({}, WS);
  const req = openReq("agt_h", { purpose: "history" });
  const out = await r.call("agent.open.before", req);
  assert.deepEqual(out, req.request);
  assert.equal(r.nodes().length, 0);
});

test("an agent without a workspace goes to an unassigned workspace", async () => {
  const r = mk();
  const out = await r.call("agent.open.before", openReq("agt_1", { workspaceId: null, cwd: "/tmp/loose" }));
  assert.match(out.env.AWT_DIR, /workspaces\/unassigned-loose\/tasks\/main\/agents\//);
});

test("current-task pointer set with the CLI redirects new agents", async () => {
  const r = mk({}, WS);
  await r.call("workspace.create.after", { workspace: { id: "wks_1", projectId: "prj_1", cwd: "/tmp/parsekit", name: "main", archivedAt: null } });
  const ws = join(r.root, r.nodes().find((x) => x.key === "paseo:workspace/wks_1")!.path);
  r.awt(ws, "init", "--kind", "task", "--name", "retry bug", "--key", "paseo:task/wks_1/retry", "--goal", "fix retries", "--done", "merged");
  r.awt(ws, "state", "--scope", "current-task", "--now", "paseo:task/wks_1/retry", "--next", "-");
  const out = await r.call("agent.open.before", openReq("agt_9"));
  assert.match(out.env.AWT_DIR, /tasks\/retry-bug\/agents\//);
});

test("P12 the lockfile resolves every package from registry.npmjs.org", () => {
  const lock = JSON.parse(readFileSync(join(import.meta.dirname, "..", "package-lock.json"), "utf8"));
  const urls = Object.values<{ resolved?: string }>(lock.packages).map((p) => p.resolved).filter((u): u is string => !!u);
  assert.ok(urls.length > 0);
  const bad = urls.filter((u) => new URL(u).host !== "registry.npmjs.org");
  assert.deepEqual(bad, []);
});

test("P13 the project display name labels the workspace", async () => {
  const r = mk({}, WS);
  await r.call("workspace.create.after", { workspace: { id: "wks_1", projectId: "prj_1", cwd: "/tmp/other", name: "main", archivedAt: null } });
  const ws = r.nodes().find((x) => x.key === "paseo:workspace/wks_1")!;
  assert.equal(ws.path, "workspaces/parsekit-main");
});
