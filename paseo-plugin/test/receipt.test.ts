import assert from "node:assert/strict";
import { test, afterEach } from "node:test";
import { agentPayload, openReq, rig, type Rig } from "./harness.js";
import { RECEIPT_KIND, RECEIPT_VERSION, parseReceipt, receiptLine } from "../shared/receipt.js";

const rigs: Rig[] = [];
const mk = (...a: Parameters<typeof rig>) => {
  const r = rig(...a);
  rigs.push(r);
  return r;
};
afterEach(() => rigs.splice(0).forEach((r) => r.cleanup()));
const WS = { wks_1: { name: "main", directory: "/tmp/parsekit", projectId: "prj_1" } };
const done = { kind: "completed" };

const begin = (r: Rig, id: string, turnId: string, over: Record<string, unknown> = {}) => r.call("agent.turn.before", { agent: agentPayload(id, over), turnId });
const end = (r: Rig, id: string, turnId: string, outcome: unknown = done, over: Record<string, unknown> = {}) =>
  r.call("agent.turn.after", { agent: agentPayload(id, over), turnId, outcome, timeline: [] });

test("P15 a turn that wrote a decision and a note appends one receipt with matching counts and ids", async () => {
  const r = mk({}, WS);
  const open = await r.call("agent.open.before", openReq("agt_1"));
  await begin(r, "agt_1", "t1");
  const d = r.awt(open.env.AWT_DIR, "decide", "Retry with jitter", "--why", "Fixed backoff synchronised the clients", "--related", "0").split(" ")[0];
  const n = r.awt(open.env.AWT_DIR, "note", "CI retries flaky tests twice").split(" ")[0];
  await end(r, "agt_1", "t1");
  assert.equal(r.appended.length, 1);
  const { id, item } = r.appended[0];
  assert.equal(id, "agt_1");
  assert.equal(item.type, "plugin");
  assert.equal(item.kind, RECEIPT_KIND);
  assert.equal(item.version, RECEIPT_VERSION);
  assert.equal(item.data.node, open.env.AWT_DIR.split("/").pop());
  assert.deepEqual(item.data.counts, { decision: 1, note: 1 });
  assert.deepEqual([...item.data.ids].sort(), [d, n].sort());
  assert.equal(item.data.auto, false);
  assert.equal(item.data.empty, false);
  assert.match(receiptLine(item.data), new RegExp(`^awt · 1 decision ${d} · 1 note$`));
  // rows written before the turn began are not counted
  await begin(r, "agt_1", "t2");
  await end(r, "agt_1", "t2");
  assert.equal(r.appended[1].item.data.empty, true);
});

test("P15 the receipt names at most 5 ids and counts a subagent's rows under the agent", async () => {
  const r = mk({}, WS);
  const open = await r.call("agent.open.before", openReq("agt_1"));
  const sub = await r.call("agent.open.before", openReq("agt_2", { labels: { "paseo.parent-agent-id": "agt_1" } }));
  await r.call("agent.create.after", { agent: agentPayload("agt_2", { parentAgentId: "agt_1" }) });
  await begin(r, "agt_1", "t1");
  for (let i = 0; i < 7; i++) r.awt(open.env.AWT_DIR, "note", `parsekit tokenizer case ${i}`);
  r.awt(sub.env.AWT_DIR, "note", "from the subagent");
  await end(r, "agt_1", "t1");
  const data = r.appended.find((a) => a.id === "agt_1")!.item.data;
  assert.equal(data.counts.note, 8);
  assert.equal(data.ids.length, 5);
});

test("P15 failed and canceled turns, and subagent turns, get a receipt too", async () => {
  const r = mk({}, WS);
  await r.call("agent.open.before", openReq("agt_1"));
  await r.call("agent.open.before", openReq("agt_2", { labels: { "paseo.parent-agent-id": "agt_1" } }));
  for (const outcome of [{ kind: "failed", error: { message: "x" } }, { kind: "canceled", reason: "user" }]) {
    await begin(r, "agt_1", "t");
    await end(r, "agt_1", "t", outcome);
  }
  await begin(r, "agt_2", "t", { parentAgentId: "agt_1" });
  await end(r, "agt_2", "t", done, { parentAgentId: "agt_1" });
  assert.deepEqual(r.appended.map((a) => a.id), ["agt_1", "agt_1", "agt_2"]);
});

test("P16 a turn that wrote nothing says so; AWT_RECEIPT=changes and =0 append nothing", async () => {
  const on = mk({}, WS);
  await on.call("agent.open.before", openReq("agt_1"));
  await begin(on, "agt_1", "t1");
  await end(on, "agt_1", "t1");
  assert.equal(on.appended.length, 1);
  assert.deepEqual(on.appended[0].item.data, { node: on.appended[0].item.data.node, counts: {}, ids: [], auto: false, empty: true });
  assert.equal(receiptLine(on.appended[0].item.data), "awt · nothing stored this turn");

  for (const mode of ["changes", "0", "off"]) {
    const r = mk({ AWT_RECEIPT: mode }, WS);
    const open = await r.call("agent.open.before", openReq("agt_1"));
    await begin(r, "agt_1", "t1");
    await end(r, "agt_1", "t1");
    assert.equal(r.appended.length, 0, mode);
    await begin(r, "agt_1", "t2");
    r.awt(open.env.AWT_DIR, "note", "something happened");
    await end(r, "agt_1", "t2");
    assert.equal(r.appended.length, mode === "changes" ? 1 : 0, mode);
  }
});

test("P16 AWT_RECEIPT=changes hides a receipt whose only row is the stand-in handoff; an unknown value shows receipts and logs once", async () => {
  const r = mk({ AWT_RECEIPT: "changes" }, WS);
  await r.call("agent.open.before", openReq("agt_1"));
  r.said.set("agt_1", ["Fixed the tokenizer; tests green."]);
  await begin(r, "agt_1", "t1");
  await end(r, "agt_1", "t1");
  assert.equal(r.appended.length, 0);

  const bad = mk({ AWT_RECEIPT: "sometimes" }, WS);
  await bad.call("agent.open.before", openReq("agt_1"));
  await begin(bad, "agt_1", "t1");
  await end(bad, "agt_1", "t1");
  assert.equal(bad.appended.length, 1);
  assert.equal(bad.logs.filter((l) => /AWT_RECEIPT/.test(l)).length, 1);
});

test("P17 the receipt comes after the stand-in handoff and marks it auto", async () => {
  const r = mk({}, WS);
  await r.call("agent.open.before", openReq("agt_1"));
  r.said.set("agt_1", ["Fixed the tokenizer; tests green."]);
  await begin(r, "agt_1", "t1");
  await end(r, "agt_1", "t1");
  assert.equal(r.appended.length, 1);
  const data = r.appended[0].item.data;
  assert.equal(data.auto, true);
  assert.equal(data.empty, false);
  assert.deepEqual(data.counts, { state: 1 });
  assert.equal(receiptLine(data), "awt · handoff [auto]");
});

test("P17 a handoff the agent wrote is not marked auto", async () => {
  const r = mk({}, WS);
  const open = await r.call("agent.open.before", openReq("agt_1"));
  await begin(r, "agt_1", "t1");
  r.awt(open.env.AWT_DIR, "state", "--now", "did x", "--next", "do y");
  await end(r, "agt_1", "t1");
  assert.equal(r.appended[0].item.data.auto, false);
  assert.equal(receiptLine(r.appended[0].item.data), "awt · handoff");
});

test("P18 an append that throws is logged and the turn is unaffected", async () => {
  const r = mk({}, WS);
  const open = await r.call("agent.open.before", openReq("agt_1"));
  r.said.set("agt_1", ["hello"]);
  r.failAppend.on = true;
  await begin(r, "agt_1", "t1");
  await end(r, "agt_1", "t1"); // resolves
  assert.ok(r.logs.some((l) => /receipt/.test(l) && /append refused/.test(l)), r.logs.join("\n"));
  assert.equal(r.rows(open.env.AWT_DIR, "state").length, 1); // the handoff stands
  assert.equal(r.sent.length, 0);
});

test("P19 AWT_RELATED in the daemon env reaches the agent env", async () => {
  const r = mk({ AWT_RELATED: "5" }, WS);
  const open = await r.call("agent.open.before", openReq("agt_1"));
  assert.equal(open.env.AWT_RELATED, "5");
  assert.equal(open.env.KEEP, "1");
  for (const unset of [undefined, ""]) {
    const plain = mk({ AWT_RELATED: unset }, WS); // undefined removes the key from the rig's env; the global process.env is left alone
    const none = await plain.call("agent.open.before", openReq("agt_1"));
    assert.equal("AWT_RELATED" in none.env, false, JSON.stringify(unset));
  }
});

test("P20 the auto handoff renders apart from handoffs the agent wrote", () => {
  const base = { node: "chat-1", counts: { state: 2 }, ids: [], auto: true, empty: false };
  assert.equal(receiptLine(base), "awt · 1 handoff · handoff [auto]");
  assert.equal(receiptLine({ ...base, counts: { state: 3 } }), "awt · 2 handoffs · handoff [auto]");
  assert.equal(receiptLine({ ...base, counts: { state: 1 } }), "awt · handoff [auto]");
  assert.equal(receiptLine({ ...base, counts: { state: 1 }, auto: false }), "awt · handoff");
  assert.equal(receiptLine({ ...base, counts: { state: 2 }, auto: false }), "awt · 2 handoffs");
});

test("P20 the renderer schema rejects an unknown version or bad data without throwing", () => {
  const good = { type: "plugin", kind: RECEIPT_KIND, version: 1, data: { node: "chat-1", counts: { decision: 1 }, ids: ["d-9e01b2c3"], auto: false, empty: false } };
  assert.equal(parseReceipt(good)?.node, "chat-1");
  assert.equal(parseReceipt({ ...good, version: 2 }), null);
  for (const data of [null, "x", {}, { ...good.data, counts: { decision: "1" } }, { ...good.data, ids: [1] }, { ...good.data, auto: "yes" }]) {
    assert.equal(parseReceipt({ ...good, data }), null);
  }
  assert.equal(parseReceipt(undefined), null);
  assert.equal(receiptLine(good.data), "awt · 1 decision d-9e01b2c3");
  assert.equal(receiptLine({ ...good.data, counts: { decision: 2, note: 1, state: 1 }, ids: ["d-1", "d-2", "n-1"], auto: true }), "awt · 2 decisions · 1 note · handoff [auto]");
});

test("P21 after a plugin restart, an agent whose node exists gets the auto handoff and a receipt; one with no node gets neither", async () => {
  const r = mk({}, WS);
  const open = await r.call("agent.open.before", openReq("agt_1"));
  r.restart(); // new process: no agent.open.before seen for agt_1
  r.said.set("agt_1", ["Fixed the tokenizer; tests green."]);
  r.said.set("agt_9", ["Nothing tracked here."]);
  await begin(r, "agt_1", "t1");
  await end(r, "agt_1", "t1");
  const st = r.rows(open.env.AWT_DIR, "state");
  assert.equal(st.length, 1);
  assert.equal(st[0].scope, "auto");
  assert.equal(r.appended.filter((a) => a.id === "agt_1").length, 1);
  // no node for agt_9, never opened: neither
  await begin(r, "agt_9", "t1");
  await end(r, "agt_9", "t1");
  assert.equal(r.appended.filter((a) => a.id === "agt_9").length, 0);
  assert.equal(r.nodes().some((n) => n.key === "paseo:agent/agt_9"), false);
  // a turn whose turn.before was missed gets nothing, the next turn works
  r.restart();
  const before = r.appended.length;
  await end(r, "agt_1", "t2");
  assert.equal(r.appended.length, before);
});
