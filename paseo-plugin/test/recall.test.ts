import assert from "node:assert/strict";
import { test, afterEach } from "node:test";
import { appendFileSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AWT, agentPayload, openReq, rig, type Rig } from "./harness.js";
import { receiptLine, parseReceipt, RECEIPT_VERSION } from "../shared/receipt.js";
import { readConfig } from "../server/config.js";
import { AWT_BLOCK } from "../server/prompt.js";

const rigs: Rig[] = [];
const mk = (...a: Parameters<typeof rig>) => {
  const r = rig(...a);
  rigs.push(r);
  return r;
};
afterEach(() => rigs.splice(0).forEach((r) => r.cleanup()));
const WS = { wks_1: { name: "main", directory: "/tmp/parsekit", projectId: "prj_1" } };
const RARE = "zorblax quenvik vamptro drelmin kosbet";
const PROMPT = `please look at ${RARE} today`;

const begin = (r: Rig, id: string, turnId: string) => r.call("agent.turn.before", { agent: agentPayload(id), turnId });
const end = (r: Rig, id: string, turnId: string) => r.call("agent.turn.after", { agent: agentPayload(id), turnId, outcome: { kind: "completed" }, timeline: [] });

/** An agent with a related note in its workspace (same Paseo project), enough filler for the idf gate, and a turn begun. */
async function world(env: Record<string, string | undefined> = { AWT_RECALL: "on" }) {
  const r = mk(env, WS);
  const open = await r.call("agent.open.before", openReq("agt_1"));
  const ws = r.nodes().find((n) => n.kind === "workspace")!;
  const wsDir = join(r.root, ws.path);
  const id = r.awt(wsDir, "note", `${RARE} the parsekit retry notes`).split(" ")[0];
  const rows = Array.from({ length: 120 }, (_, i) => JSON.stringify({ v: 1, ts: new Date().toISOString(), type: "note", host: "h", by: "t", id: `n-f${String(i).padStart(7, "0")}`, text: `filler${i} unrelated` }));
  appendFileSync(join(wsDir, ".awt", "events.jsonl"), rows.join("\n") + "\n");
  await begin(r, "agt_1", "t1");
  return { r, open, id, dir: open.env.AWT_DIR as string };
}

test("PRP1 AWT_RECALL and AWT_RECALL_SCOPE in the daemon env reach the agent env; unset stays unset", async () => {
  const r = mk({ AWT_RECALL: "on", AWT_RECALL_SCOPE: "workspace" }, WS);
  const open = await r.call("agent.open.before", openReq("agt_1"));
  assert.equal(open.env.AWT_RECALL, "on");
  assert.equal(open.env.AWT_RECALL_SCOPE, "workspace");
  const plain = mk({ AWT_RECALL: undefined, AWT_RECALL_SCOPE: undefined }, WS);
  const none = await plain.call("agent.open.before", openReq("agt_1"));
  assert.equal("AWT_RECALL" in none.env, false);
  assert.equal("AWT_RECALL_SCOPE" in none.env, false);
  assert.equal(readConfig({}).recall, null);
});

test("PRP2 a turn with a prompt recall row has a receipt with recalled, no recall in counts, and empty stays true", async () => {
  const { r, dir, id } = await world();
  r.awt(dir, "find", "--like", PROMPT, "--hook");
  assert.equal(r.rows(dir, "recall").length, 1);
  await end(r, "agt_1", "t1");
  const data = r.appended[0].item.data;
  assert.deepEqual(data.recalled.map((x: any) => x.id), [id]);
  assert.ok(!("recall" in data.counts));
  assert.equal(data.empty, true);
  assert.equal(data.shadow, undefined);
  assert.match(receiptLine(data), new RegExp(`^awt · recalled ${id} "[^"]+" · nothing stored this turn$`));
});

test("PRP3 AWT_RECEIPT=changes shows a recall-only receipt; a turn with neither recall nor writes shows none", async () => {
  const { r, dir } = await world({ AWT_RECALL: "on", AWT_RECEIPT: "changes" });
  await end(r, "agt_1", "t1");
  assert.equal(r.appended.length, 0);
  await begin(r, "agt_1", "t2");
  r.awt(dir, "find", "--like", PROMPT, "--hook");
  await end(r, "agt_1", "t2");
  assert.equal(r.appended.length, 1);
});

test("PRP4 a shadow row (and an every row) shows as would recall, with shadow true", async () => {
  const { r, dir, id } = await world({ AWT_RECALL: "shadow" });
  r.awt(dir, "find", "--like", PROMPT, "--hook");
  r.awt(dir, "find", "--like", PROMPT, "--hook"); // an every row
  assert.deepEqual(r.rows(dir, "recall").map((x) => x.trigger), ["prompt", "every"]);
  await end(r, "agt_1", "t1");
  const data = r.appended[0].item.data;
  assert.equal(data.shadow, true);
  assert.deepEqual(data.recalled.map((x: any) => x.id), [id]);
  assert.match(receiptLine(data), new RegExp(`^awt · would recall ${id} "[^"]+" \\(shadow\\) · nothing stored this turn$`));
});

test("PRP5 a version 1 receipt without the new keys still renders, and one with them parses under the old schema", () => {
  const old = { node: "chat-1", counts: { note: 1 }, ids: [], auto: false, empty: false };
  assert.equal(receiptLine(parseReceipt({ version: RECEIPT_VERSION, data: old })!), "awt · 1 note");
  const withNew = parseReceipt({ version: RECEIPT_VERSION, data: { ...old, recalled: [{ id: "d-7f3a9c21", text: "x" }], shadow: true, extra: 1 } });
  assert.ok(withNew);
  assert.equal(receiptLine({ ...old, recalled: [{ id: "d-7f3a9c21", text: "Retry with jitter" }] }), 'awt · recalled d-7f3a9c21 "Retry with jitter" · 1 note');
  assert.equal(receiptLine({ ...old, recalled: [{ id: "d-7f3a9c21" }] }), "awt · recalled d-7f3a9c21 · 1 note");
});

test("PRP6 the prompt block says nothing about recall", () => {
  assert.doesNotMatch(AWT_BLOCK, /recall/i);
});

test("PRP7 recalled carries {id, text} with text at most 80 chars from awt find --tree ID, never stored", async () => {
  const { r, dir, id } = await world();
  r.awt(join(r.root, r.nodes().find((n) => n.kind === "workspace")!.path), "note", `${RARE} ${"long ".repeat(40)}`);
  r.awt(dir, "find", "--like", PROMPT, "--hook");
  await end(r, "agt_1", "t1");
  const rec = r.appended[0].item.data.recalled as { id: string; text?: string }[];
  assert.ok(rec.length >= 1);
  for (const x of rec) assert.ok(x.text !== undefined && x.text.length > 0 && x.text.length <= 80, JSON.stringify(x));
  assert.ok(rec.find((x) => x.id === id)!.text!.includes("zorblax"));
  const row = r.rows(dir, "recall")[0];
  assert.deepEqual(Object.keys(row).sort(), ["by", "chars", "host", "ids", "model", "result", "trigger", "ts", "type", "v"].sort());
  assert.ok(!JSON.stringify(r.rows(dir)).includes("retry notes"));
});

test("PRP7 a failing text fetch leaves the id without text", async () => {
  const dir0 = mkdtempSync(join(tmpdir(), "awtbin-"));
  const wrap = join(dir0, "awt");
  writeFileSync(wrap, `#!/bin/sh\ncase " $* " in *" find --tree "*) exit 1;; esac\nexec ${AWT} "$@"\n`, { mode: 0o755 });
  try {
    const { r, dir, id } = await world({ AWT_RECALL: "on", AWT_BIN: wrap });
    r.awt(dir, "find", "--like", PROMPT, "--hook");
    await end(r, "agt_1", "t1");
    assert.deepEqual(r.appended[0].item.data.recalled, [{ id }]);
  } finally {
    rmSync(dir0, { recursive: true, force: true });
  }
});
