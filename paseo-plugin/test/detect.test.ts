import assert from "node:assert/strict";
import { test, afterEach } from "node:test";
import { agentPayload, openReq, rig, type Rig } from "./harness.js";
import { callEvents, permissionEvent, resendReason } from "../server/detect.js";
import { RESEND_KIND, parseResend } from "../shared/resend.js";

const rigs: Rig[] = [];
const mk = (...a: Parameters<typeof rig>) => {
  const r = rig(...a);
  rigs.push(r);
  return r;
};
afterEach(() => rigs.splice(0).forEach((r) => r.cleanup()));
const WS = { wks_1: { name: "main", directory: "/tmp/parsekit", projectId: "prj_1" } };

const shellAsk = (id: string, reqId: string, command: string, over: Record<string, unknown> = {}) => ({
  agent: agentPayload(id),
  request: { id: reqId, provider: "claude", name: "Bash", kind: "tool", title: command, detail: { type: "shell", command, cwd: "/tmp/parsekit" }, ...over },
});
const call = (callId: string, command: string, status = "completed", exitCode: number | null = 0) => ({
  type: "tool_call", id: "i-" + callId, callId, name: "Bash", status, error: status === "failed" ? "boom" : null, detail: { type: "shell", command, cwd: "/tmp/parsekit", exitCode },
});
const effects = (r: Rig, dir: string) => r.rows(dir, "effect");
const opened = async (r: Rig, id: string) => (await r.call("agent.open.before", openReq(id))).env.AWT_DIR as string;
const turn = async (r: Rig, id: string, items: unknown[]) => {
  r.items.set(id, items);
  await r.call("agent.turn.before", { agent: agentPayload(id), turnId: "t" });
  await r.call("agent.turn.after", { agent: agentPayload(id), turnId: "t", outcome: { kind: "completed" }, timeline: [] });
};

test("D1 a shell permission request for git push is recorded; the plugin answers nothing", async () => {
  const r = mk({}, WS);
  const dir = await opened(r, "agt_1");
  await r.call("agent.permission.before", shellAsk("agt_1", "perm-1", "git push origin feat/x"));
  const rows = effects(r, dir);
  assert.deepEqual(rows.map((x) => x.step), ["planned", "begun"]);
  assert.deepEqual([rows[0].origin, rows[0].rule, rows[0].seen, rows[0].by], ["detected", "git push", "before", "agt_1"]);
  assert.deepEqual(r.answered, []);
});

test("D2 the turn scan settles it as sent, pairing by key although the ids differ", async () => {
  const r = mk({}, WS);
  const dir = await opened(r, "agt_1");
  await r.call("agent.permission.before", shellAsk("agt_1", "perm-1", "git push origin feat/x"));
  await turn(r, "agt_1", [call("c1", "git push origin feat/x")]);
  assert.deepEqual(effects(r, dir).map((x) => x.step), ["planned", "begun", "sent"]);
  await turn(r, "agt_1", [call("c1", "git push origin feat/x")]); // the same page again
  assert.equal(effects(r, dir).length, 3);
});

test("D3 a request that repeats a sent effect appends a resend note naming it, and still never denies", async () => {
  const r = mk({}, WS);
  const dir = await opened(r, "agt_1");
  await r.call("agent.permission.before", shellAsk("agt_1", "perm-1", "gh pr comment 12 --body-file b.md"));
  await turn(r, "agt_1", [call("c1", "gh pr comment 12 --body-file b.md")]);
  const id = effects(r, dir)[0].id;
  r.appended.length = 0;
  await r.call("agent.permission.before", shellAsk("agt_1", "perm-2", "gh  pr comment 12 --body-file b.md"));
  const note = r.appended.find((a) => a.item.kind === RESEND_KIND);
  assert.ok(note, "a resend note");
  assert.match(parseResend(note!.item)!.reason, new RegExp(id));
  assert.deepEqual(r.answered, []);
  assert.equal(effects(r, dir).length, 3, "the resend itself is recorded only if it goes ahead");
});

test("D4 an auto-allowed call (no permission request) is recorded after the fact", async () => {
  const r = mk({}, WS);
  const dir = await opened(r, "agt_1");
  await turn(r, "agt_1", [call("c1", "gh pr create --title t"), call("c2", "ls -la"), call("c3", "git status")]);
  const rows = effects(r, dir);
  assert.deepEqual(rows.map((x) => x.step), ["planned", "begun", "sent"]);
  assert.equal(rows[0].seen, "after");
  assert.equal(rows[0].rule, "gh pr create");
});

test("D5 a failed or canceled call is unknown; a running one is left for a later turn", async () => {
  const r = mk({}, WS);
  const dir = await opened(r, "agt_1");
  await turn(r, "agt_1", [call("c1", "git push", "failed", 1), call("c2", "npm publish", "canceled"), call("c3", "cargo publish", "running"), call("c4", "twine upload d/*", "completed", 2)]);
  const last = (rule: string) => effects(r, dir).filter((x) => x.id === effects(r, dir).find((y) => y.rule === rule)!.id).map((x) => x.step).pop();
  assert.equal(last("git push"), "unknown");
  assert.equal(last("npm publish"), "unknown");
  assert.equal(last("twine upload"), "unknown");
  assert.equal(effects(r, dir).find((x) => x.rule === "cargo publish"), undefined);
  await turn(r, "agt_1", [call("c3", "cargo publish")]); // now finished
  assert.equal(effects(r, dir).filter((x) => x.rule === "cargo publish").length, 1);
});

test("D6 MCP calls are labelled by tool name and keyed on their input", async () => {
  const r = mk({}, WS);
  const dir = await opened(r, "agt_1");
  const mcp = { type: "tool_call", id: "i1", callId: "m1", name: "mcp__slack__post_message", status: "completed", error: null, detail: { type: "unknown", input: { channel: "#eng", text: "hi" }, output: null } };
  await turn(r, "agt_1", [mcp, { ...mcp, id: "i2", callId: "m2", name: "mcp__slack__list_channels" }]);
  assert.deepEqual(effects(r, dir).map((x) => x.rule).filter(Boolean), ["mcp:mcp__slack__post_message"]);
  await r.call("agent.permission.before", { agent: agentPayload("agt_1"), request: { id: "p2", provider: "claude", name: "mcp__slack__post_message", kind: "tool", input: { channel: "#eng", text: "hi" } } });
  assert.ok(r.appended.some((a) => a.item.kind === RESEND_KIND));
});

test("D7 requests awt cannot read are left alone: opencode 2.x shape, agent with no node, awt missing", async () => {
  const r = mk({}, WS);
  const dir = await opened(r, "agt_1");
  // opencode 2.x: `name` is the action, no `input`, no `detail` (docs/e2e-provider-gaps.md, fact 6)
  await r.call("agent.permission.before", { agent: agentPayload("agt_1"), request: { id: "p1", provider: "opencode", name: "bash", kind: "tool", title: "git push" } });
  await r.call("agent.permission.before", { agent: agentPayload("agt_1"), request: { id: "p2", provider: "opencode", name: "external_directory", kind: "tool", metadata: { resources: [dir + "/*"] } } });
  await r.call("agent.permission.before", shellAsk("agt_nobody", "p3", "git push"));
  assert.deepEqual(effects(r, dir), []);
  assert.deepEqual(r.answered, []);
  const bad = mk({ AWT_BIN: "/nonexistent/awt" }, WS);
  await assert.doesNotReject(bad.call("agent.permission.before", shellAsk("agt_1", "p4", "git push")));
  // ...but the turn scan still sees the call that raised that request
  await turn(r, "agt_1", [call("c1", "git push")]);
  assert.equal(effects(r, dir).length, 3);
});

test("D8 a native subagent's calls inside a sub_agent item are not seen (known gap), and nothing throws", async () => {
  const r = mk({}, WS);
  const dir = await opened(r, "agt_1");
  await turn(r, "agt_1", [{ type: "sub_agent", id: "s1", status: "completed", description: "push it", log: "git push origin main" }]);
  assert.deepEqual(effects(r, dir), []);
});

test("D9 permissionEvent and callEvents read only what they understand", () => {
  assert.equal(permissionEvent({ cwd: "/w" }, null), null);
  assert.equal(permissionEvent({ cwd: "/w" }, { id: "x", name: "Read", detail: { type: "read", filePath: "/a" } }), null);
  assert.deepEqual(permissionEvent({ cwd: "/w" }, { id: "x", name: "Bash", detail: { type: "shell", command: "git push" } }), { phase: "before", tool: "Bash", input: { command: "git push" }, cwd: "/w", id: "x" });
  assert.deepEqual(callEvents({ entries: [{ item: call("c", "git push", "completed", null) }] }, {}).map((e) => e.ok), [true]);
  assert.deepEqual(callEvents("nope", {}), []);
  assert.equal(resendReason("{}"), null);
  assert.equal(resendReason("not json"), null);
  assert.equal(resendReason(JSON.stringify({ hookSpecificOutput: { permissionDecision: "ask", permissionDecisionReason: "why" } })), "why");
});

test("D10 the detect ingest call carries the agent's model (--model), at permission time and in the turn scan", async () => {
  const r = mk({}, WS);
  r.runtime.set("agt_1", "claude-sonnet-5-5");
  const dir = await opened(r, "agt_1");
  await r.call("agent.permission.before", shellAsk("agt_1", "perm-1", "git push origin feat/x"));
  assert.deepEqual(effects(r, dir).map((x) => x.model), ["claude-sonnet-5-5", "claude-sonnet-5-5"]);
  await turn(r, "agt_1", [call("c1", "git push origin feat/x")]);
  assert.deepEqual(new Set(effects(r, dir).map((x) => x.model)), new Set(["claude-sonnet-5-5"]));
});

test("D11 a denied permission puts the begun effect back to not-sent; an allowed one changes nothing", async () => {
  const r = mk({}, WS);
  const dir = await opened(r, "agt_1");
  await r.call("agent.permission.before", shellAsk("agt_1", "perm-1", "gh pr merge 4 --squash"));
  await r.call("agent.permission.after", { agent: agentPayload("agt_1"), requestId: "perm-1", resolution: { behavior: "allow" } });
  assert.deepEqual(effects(r, dir).map((x) => x.step), ["planned", "begun"]);
  await r.call("agent.permission.before", shellAsk("agt_1", "perm-2", "gh pr merge 5 --squash"));
  await r.call("agent.permission.after", { agent: agentPayload("agt_1"), requestId: "perm-2", resolution: { behavior: "deny" } });
  const id5 = effects(r, dir).find((x) => x.how?.includes("merge 5")).id;
  const rows = effects(r, dir).filter((x) => x.id === id5);
  assert.deepEqual(rows.map((x) => x.step), ["planned", "begun", "planned"]);
  assert.equal(r.awt(dir, "effect", "show", rows[0].id).includes("state: planned"), true);
});
