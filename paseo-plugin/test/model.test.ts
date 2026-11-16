import assert from "node:assert/strict";
import { test, afterEach } from "node:test";
import { agentPayload, openReq, rig, type Rig } from "./harness.js";

const rigs: Rig[] = [];
const mk = (...a: Parameters<typeof rig>) => {
  const r = rig(...a);
  rigs.push(r);
  return r;
};
afterEach(() => rigs.splice(0).forEach((r) => r.cleanup()));
const WS = { wks_1: { name: "main", directory: "/tmp/parsekit", projectId: "prj_1" } };
const create = (r: Rig, model: string | undefined, over: Record<string, unknown> = {}) =>
  r.call("agent.create.before", { request: { config: { provider: "claude", cwd: "/tmp/parsekit", title: "Chat a1", ...(model ? { model } : {}), ...over }, env: { PARSEKIT_ENV: "dev" } } });
const agentRows = (r: Rig, id: string, type: string) => r.rows(r.root + "/" + r.nodes().find((x) => x.key === `paseo:agent/${id}`)!.path, type);

test("M1 the configured model reaches the agent env as AWT_MODEL", async () => {
  const r = mk({}, WS);
  const made = await create(r, "claude-sonnet-5-5");
  assert.equal(made.env.AWT_MODEL, "claude-sonnet-5-5");
  assert.equal(made.env.PARSEKIT_ENV, "dev");
  const out = await r.call("agent.open.before", openReq("a1"));
  assert.equal(out.env.AWT_MODEL, "claude-sonnet-5-5");
});

test("M2 a provider-default agent gets <provider>:default when Paseo reports no model", async () => {
  const r = mk({}, WS);
  await create(r, undefined);
  const out = await r.call("agent.open.before", openReq("a1"));
  assert.equal(out.env.AWT_MODEL, "claude:default");
});

test("M3 a resolved runtime model wins over the configured one, on a reopen", async () => {
  const r = mk({}, WS);
  r.runtime.set("a1", "us.anthropic.claude-sonnet-5-5-v1:0");
  const out = await r.call("agent.open.before", openReq("a1", { reason: "resume" }));
  assert.equal(out.env.AWT_MODEL, "us.anthropic.claude-sonnet-5-5-v1:0");
});

test("M4 the plugin's own writes carry the agent's model", async () => {
  const r = mk({}, WS);
  await create(r, "claude-sonnet-5-5");
  await r.call("agent.open.before", openReq("a1"));
  await r.call("agent.create.after", { agent: agentPayload("a1") });
  await r.call("agent.turn.before", { agent: agentPayload("a1"), turnId: "t1" });
  r.said.set("a1", ["parsekit tokenizer done"]);
  await r.call("agent.turn.after", { agent: agentPayload("a1"), turnId: "t1", outcome: { kind: "completed" }, timeline: [] });
  const states = agentRows(r, "a1", "state");
  assert.ok(states.some((x) => x.scope === "auto"));
  for (const x of states) assert.equal(x.model, "claude-sonnet-5-5", JSON.stringify(x));
  for (const x of agentRows(r, "a1", "task")) assert.equal(x.model, "claude-sonnet-5-5");
});

test("M5 a model change mid-agent shows in later plugin writes", async () => {
  const r = mk({}, WS);
  await create(r, "claude-sonnet-5-5");
  await r.call("agent.open.before", openReq("a1"));
  r.runtime.set("a1", "claude-opus-5-5");
  await r.call("agent.turn.before", { agent: agentPayload("a1"), turnId: "t1" });
  await r.call("agent.turn.after", { agent: agentPayload("a1"), turnId: "t1", outcome: { kind: "completed" }, timeline: [] }); // no text said: no write
  r.said.set("a1", ["now on opus"]);
  await r.call("agent.turn.before", { agent: agentPayload("a1"), turnId: "t2" });
  await r.call("agent.turn.after", { agent: agentPayload("a1"), turnId: "t2", outcome: { kind: "completed" }, timeline: [] });
  const auto = agentRows(r, "a1", "state").filter((x) => x.scope === "auto");
  assert.equal(auto.at(-1).model, "claude-opus-5-5");
});

test("M6 two agents keep their own models", async () => {
  const r = mk({}, WS);
  await create(r, "claude-sonnet-5-5", { title: "Chat a1" });
  const a = await r.call("agent.open.before", openReq("a1"));
  await create(r, "claude-opus-5-5", { title: "Chat a2" });
  const b = await r.call("agent.open.before", openReq("a2"));
  assert.equal(a.env.AWT_MODEL, "claude-sonnet-5-5");
  assert.equal(b.env.AWT_MODEL, "claude-opus-5-5");
});

test("M7 no write carries unknown:unset when the model is known", async () => {
  const r = mk({}, WS);
  await create(r, "claude-sonnet-5-5");
  await r.call("agent.open.before", openReq("a1"));
  await r.call("agent.archive.after", { agent: agentPayload("a1"), archivedAt: "2026-11-16T00:00:00Z" });
  const bad = [...agentRows(r, "a1", "status"), ...agentRows(r, "a1", "task")].filter((x) => x.model === "unknown:unset");
  assert.deepEqual(bad, []);
});
