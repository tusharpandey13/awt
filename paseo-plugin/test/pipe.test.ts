// The Paseo pipe: turn outcomes, models and permissions go to `awt ingest --source paseo --stdin` (SPEC.md, "Paseo pipe").
import assert from "node:assert/strict";
import { test, afterEach } from "node:test";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { agentPayload, openReq, rig, type Rig } from "./harness.js";

const rigs: Rig[] = [];
const mk = (extra: Record<string, string | undefined> = { AWT_PIPE: "1" }) => {
  const r = rig(extra, { wks_1: { name: "main", directory: "/tmp/parsekit", projectId: "prj_1" } });
  rigs.push(r);
  return r;
};
afterEach(() => rigs.splice(0).forEach((r) => r.cleanup()));

/** The piped event rows of an agent in the canonical store. */
function events(r: Rig, id: string): any[] {
  const dir = join(r.store, "log", "paseo");
  let files: string[] = [];
  try {
    files = readdirSync(dir).filter((f) => f === `${id}.jsonl`);
  } catch {
    return [];
  }
  return files.flatMap((f) => readFileSync(join(dir, f), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l).raw)).filter((x) => x.event);
}

const turn = async (r: Rig, id: string, n: number, outcome: any = { kind: "completed" }) => {
  await r.call("agent.turn.before", { agent: agentPayload(id), turnId: `turn-${n}` });
  await r.call("agent.turn.after", { agent: agentPayload(id), turnId: `turn-${n}`, outcome, timeline: [] });
  await r.idle();
};

test("PP1 a turn is piped with its outcome and the model Paseo reports; a model switch shows in the next turn", async () => {
  const r = mk();
  await r.call("agent.open.before", openReq("agt_a"));
  r.models.set("agt_a", "model-one");
  await turn(r, "agt_a", 1);
  r.models.set("agt_a", "model-two");
  await turn(r, "agt_a", 2, { kind: "failed", error: { message: "boom secret", code: "provider_error" } });
  await turn(r, "agt_a", 3, { kind: "canceled", reason: "user" });
  const ev = events(r, "agt_a");
  assert.deepEqual(ev.map((e) => [e.eid, e.model, e.outcome, e.code]), [
    ["turn:agt_a:turn-1", "model-one", "completed", undefined],
    ["turn:agt_a:turn-2", "model-two", "failed", "provider_error"],
    ["turn:agt_a:turn-3", "model-two", "canceled", undefined],
  ]);
  assert.ok(ev[0].startedAt && ev[0].endedAt && ev[0].provider === "claude");
  assert.ok(!JSON.stringify(ev).includes("boom"), "the error message is not piped");
});

test("PP2 no model from Paseo is <provider>:default", async () => {
  const r = mk();
  await turn(r, "agt_a", 1);
  assert.equal(events(r, "agt_a")[0].model, "claude:default");
});

test("PP3 permissions: the request and the answer are piped; the plugin's own answer says so", async () => {
  const r = mk();
  const a = await r.call("agent.open.before", openReq("agt_a"));
  const agent = agentPayload("agt_a");
  const mine = { id: "perm-1", provider: "claude", name: "Write", kind: "tool", detail: { type: "write", filePath: join(a.env.AWT_DIR, "notes.md"), content: "x" } };
  const theirs = { id: "perm-2", provider: "claude", name: "Bash", kind: "tool", detail: { type: "shell", command: "pytest -q" } };
  await r.call("agent.permission.before", { agent, request: mine });
  await r.call("agent.permission.after", { agent, requestId: "perm-1", resolution: { behavior: "allow" } });
  await r.call("agent.permission.before", { agent, request: theirs });
  await r.call("agent.permission.after", { agent, requestId: "perm-2", resolution: { behavior: "deny" } });
  await r.idle();
  const ev = events(r, "agt_a");
  const by = (k: string) => ev.find((e) => e.eid === k);
  assert.deepEqual(r.answered.map((x) => x.requestId), ["perm-1"]);
  assert.equal(by("permres:agt_a:perm-1").decidedBy, "plugin");
  assert.equal(by("permres:agt_a:perm-1").decision, "allow");
  assert.equal(by("permres:agt_a:perm-2").decidedBy, "person");
  assert.equal(by("permres:agt_a:perm-2").decision, "deny");
  assert.equal(by("perm:agt_a:perm-2").tool, "Bash");
  assert.equal(by("perm:agt_a:perm-2").target, "pytest -q");
});

test("PP4 the pipe is off with AWT_PIPE=0 and writes nothing", async () => {
  const r = mk({ AWT_PIPE: "0" });
  await turn(r, "agt_a", 1);
  assert.deepEqual(events(r, "agt_a"), []);
});

test("PP5 a broken awt binary is logged and never fails the hook", async () => {
  const r = mk({ AWT_PIPE: "1", AWT_BIN: "/nonexistent/awt" });
  await turn(r, "agt_a", 1);
  assert.ok(r.logs.some((l) => l.includes("pipe")), r.logs.join("\n"));
});

test("PP6 a replayed turn adds nothing: the event id is stable", async () => {
  const r = mk();
  await turn(r, "agt_a", 1);
  await turn(r, "agt_a", 1);
  assert.equal(events(r, "agt_a").length, 1);
});
