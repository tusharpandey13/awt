import assert from "node:assert/strict";
import { test, afterEach } from "node:test";
import { chmodSync, cpSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, renameSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { agentPayload, AWT, openReq, rig, type Rig } from "./harness.js";

const rigs: Rig[] = [];
const mk = (...a: Parameters<typeof rig>) => {
  const r = rig(...a);
  rigs.push(r);
  return r;
};
afterEach(() => rigs.splice(0).forEach((r) => r.cleanup()));
const AKIA = "AK" + "IA" + "ABCDEFGHIJKLMNOP";
const WS = { wks_1: { name: "main", directory: "/tmp/parsekit", projectId: "prj_1" } };

function walk(dir: string, out: string[] = []): string[] {
  for (const n of readdirSync(dir)) {
    const p = join(dir, n);
    statSync(p).isDirectory() ? walk(p, out) : out.push(p);
  }
  return out;
}

test("C30 hook storm: 100 agents, each opened twice at once, no duplicates", async () => {
  const r = mk({ AWT_TIMEOUT_MS: "120000" }, WS);
  const ids = Array.from({ length: 100 }, (_, i) => `agt_${i}`);
  const outs = await Promise.all([...ids, ...ids].map((id) => r.call("agent.open.before", openReq(id))));
  const nodes = r.nodes();
  const keys = nodes.map((n) => n.key);
  assert.equal(new Set(keys).size, keys.length);
  assert.equal(nodes.filter((n) => n.kind === "agent").length, 100);
  assert.equal(nodes.filter((n) => n.kind === "task").length, 1);
  for (const id of ids) {
    const dirs = new Set(outs.filter((o) => o.env.AWT_BY === id).map((o) => o.env.AWT_DIR));
    assert.equal(dirs.size, 1, id);
  }
});

const broken: Record<string, string> = {
  missing: "",
  hang: "#!/bin/sh\nsleep 30\n",
  exit3: "#!/bin/sh\necho nope >&2\nexit 3\n",
  garbage: "#!/bin/sh\necho '{{{ not json'\nexit 0\n",
  empty: "#!/bin/sh\nexit 0\n",
};
for (const [name, script] of Object.entries(broken)) {
  test(`C31 awt ${name}: every hook returns in time and the agent is untouched`, async () => {
    const tmp = mkdtempSync(join(tmpdir(), "awtfake-"));
    const bin = name === "missing" ? join(tmp, "no-such-awt") : join(tmp, "fake-awt");
    if (name !== "missing") {
      writeFileSync(bin, script);
      chmodSync(bin, 0o755);
    }
    const r = mk({ AWT_BIN: bin, AWT_TIMEOUT_MS: "300" }, WS);
    const t0 = Date.now();
    const open = openReq("agt_1");
    const out = await r.call("agent.open.before", open);
    assert.deepEqual(out, open.request);
    await r.call("workspace.create.after", { workspace: { id: "wks_1", projectId: "p", cwd: "/x", name: "n", archivedAt: null } });
    await r.call("agent.create.after", { agent: agentPayload("agt_1") });
    await r.call("agent.turn.before", { agent: agentPayload("agt_1"), turnId: "t" });
    await r.call("agent.turn.after", { agent: agentPayload("agt_1"), turnId: "t", outcome: { kind: "completed" }, timeline: [] });
    await r.call("agent.archive.after", { agent: agentPayload("agt_1"), archivedAt: "x" });
    await r.call("workspace.archive.after", { workspace: { id: "wks_1", projectId: "p", cwd: "/x", name: "n", archivedAt: "x" } });
    const created = await r.call("agent.create.before", { request: { config: { provider: "claude", cwd: "/x" }, env: {} } });
    assert.deepEqual(created, { config: { provider: "claude", cwd: "/x" }, env: {} }); // no awt, so no instructions to use it
    assert.ok(Date.now() - t0 < 15000, `took ${Date.now() - t0} ms`);
    assert.equal(r.sent.length, 0);
  });
}

test("C32 malformed payloads never throw and never leak secrets to disk", async () => {
  const r = mk({}, WS);
  const variants: Record<string, unknown>[] = [
    { workspaceId: undefined },
    { workspaceId: null, cwd: "" },
    { cwd: undefined },
    { title: null },
    { title: "x".repeat(5000) },
    { title: `token ${AKIA}` },
    { title: "../../etc/passwd" },
    { title: "\u0000\u202e\u001b[31m" },
    { title: "日本語 😀" },
    { tools: undefined },
    { env: undefined },
  ];
  for (const [i, v] of variants.entries()) {
    const req = openReq(`agt_${i}`, v);
    for (const k of Object.keys(v)) if (v[k] === undefined) delete (req.request as any)[k];
    await r.call("agent.open.before", req).catch((e) => assert.fail(`variant ${i} threw: ${e}`));
  }
  await r.call("agent.open.before", openReq("../../escape"));
  // create.after: a parent that was never seen, null parent and labels, null title
  for (const [i, v] of [{ parentAgentId: "agt_ghost" }, { parentAgentId: null, labels: null }, { title: null, labels: null }, { parentAgentId: "../../ghost" }].entries()) {
    await r.call("agent.create.after", { agent: agentPayload(`agt_c${i}`, v) }).catch((e) => assert.fail(`create.after ${i} threw: ${e}`));
  }
  assert.equal(r.nodes().filter((n) => n.key?.startsWith("paseo:agent/agt_c")).length, 4);
  for (const f of walk(r.root)) assert.ok(!readFileSync(f, "utf8").includes(AKIA), f);
  for (const n of r.nodes()) assert.ok(!n.path.includes(".."), n.path);
});

test("C33 replayed and reordered hooks give the same tree as one ordered delivery", async () => {
  const ordered = mk({}, WS);
  const shuffled = mk({}, WS);
  const ws = { workspace: { id: "wks_1", projectId: "prj_1", cwd: "/tmp/parsekit", name: "main", archivedAt: null } };
  const steps = (r: Rig) => [
    () => r.call("workspace.create.after", ws),
    () => r.call("agent.open.before", openReq("agt_1")),
    () => r.call("agent.create.after", { agent: agentPayload("agt_1") }),
    () => r.call("agent.open.before", openReq("agt_2")),
    () => r.call("agent.create.after", { agent: agentPayload("agt_2") }),
  ];
  for (const s of steps(ordered)) await s();
  const all = steps(shuffled);
  const order = [4, 2, 0, 3, 1, 2, 0, 4, 1, 3, 0];
  for (const i of order) await all[i]();
  const shape = (r: Rig) => r.nodes().map((n) => `${n.path}|${n.kind}|${n.key}`).sort();
  assert.deepEqual(shape(shuffled), shape(ordered));
});

test("C34 an agent that never records state is nudged once, then not again until it records state", async () => {
  const r = mk({ AWT_NUDGE: "1" }, WS);
  const opened = await r.call("agent.open.before", openReq("agt_1"));
  const turn = async (i: number) => {
    await r.call("agent.turn.before", { agent: agentPayload("agt_1"), turnId: `t${i}` });
    await r.call("agent.turn.after", { agent: agentPayload("agt_1"), turnId: `t${i}`, outcome: { kind: "completed" }, timeline: [] });
  };
  for (let i = 0; i < 6; i++) await turn(i);
  assert.equal(r.sent.length, 1);
  // the agent records state during a turn: that ends the stretch, and a later silent turn is nudged once more
  await r.call("agent.turn.before", { agent: agentPayload("agt_1"), turnId: "w" });
  r.awt(opened.env.AWT_DIR, "state", "--now", "working", "--next", "more");
  await r.call("agent.turn.after", { agent: agentPayload("agt_1"), turnId: "w", outcome: { kind: "completed" }, timeline: [] });
  assert.equal(r.sent.length, 1);
  for (let i = 6; i < 9; i++) await turn(i);
  assert.equal(r.sent.length, 2);
});

test("C35 an agent without an AWT_DIR is never nudged", async () => {
  const r = mk({ AWT_NUDGE: "1" }, WS);
  await r.call("agent.turn.before", { agent: agentPayload("agt_9"), turnId: "t" });
  await r.call("agent.turn.after", { agent: agentPayload("agt_9"), turnId: "t", outcome: { kind: "completed" }, timeline: [] });
  assert.equal(r.sent.length, 0);
});

/** Copies agent `from`'s node under `into`, so two nodes carry the same key. */
function dup(r: Rig, from: string, into: string) {
  const src = r.nodes().find((n) => n.key === from)!;
  const host = r.nodes().find((n) => n.key === into)!;
  mkdirSync(join(r.root, host.path, "agents"), { recursive: true });
  cpSync(join(r.root, src.path), join(r.root, host.path, "agents", "copy"), { recursive: true });
}

test("C36 a key carried by two nodes, at two depths, is an error: logged, agent untouched", async () => {
  const r = mk({}, WS);
  for (const id of ["agt_5", "agt_7"]) await r.call("agent.open.before", openReq(id));
  dup(r, "paseo:agent/agt_5", "paseo:agent/agt_7"); // a sibling's child
  dup(r, "paseo:agent/agt_5", "paseo:task/wks_1/main"); // a direct child of the task
  assert.equal(r.nodes().filter((n) => n.key === "paseo:agent/agt_5").length, 3);
  r.restart();
  const req = openReq("agt_5");
  assert.deepEqual(await r.call("agent.open.before", req), req.request);
  assert.ok(r.logs.some((l) => l.includes("paseo:agent/agt_5")), r.logs.join("\n"));
  // an agent whose key is carried twice gets no nudge either
  await r.call("agent.turn.before", { agent: agentPayload("agt_5"), turnId: "t" });
  await r.call("agent.turn.after", { agent: agentPayload("agt_5"), turnId: "t", outcome: { kind: "completed" }, timeline: [] });
  assert.equal(r.sent.length, 0);
  const other = await r.call("agent.open.before", openReq("agt_7"));
  assert.ok(other.env.AWT_DIR.endsWith("/" + r.nodes().find((n) => n.key === "paseo:agent/agt_7")!.path.split("/").pop()));
});

test("C37 one deadline covers the whole open.before chain, not each awt call", async () => {
  const tmp = mkdtempSync(join(tmpdir(), "awtslow-"));
  const bin = join(tmp, "slow-awt");
  writeFileSync(bin, `#!/bin/sh\nsleep 0.5\nexec "${AWT}" "$@"\n`);
  chmodSync(bin, 0o755);
  const r = mk({ AWT_BIN: bin, AWT_TIMEOUT_MS: "1200" }, WS);
  const t0 = Date.now();
  const req = openReq("agt_1");
  assert.deepEqual(await r.call("agent.open.before", req), req.request); // every call works, the chain does not fit
  assert.ok(Date.now() - t0 < 2000, `took ${Date.now() - t0} ms`);
  assert.ok(r.logs.some((l) => l.includes("exceeded")), r.logs.join("\n"));
});

test("C38 a cancelled hook kills its awt children", async () => {
  const tmp = mkdtempSync(join(tmpdir(), "awtcancel-"));
  const bin = join(tmp, "fake-awt");
  writeFileSync(bin, `#!/bin/sh\necho started >> "${tmp}/log"\nsleep 30\n`);
  chmodSync(bin, 0o755);
  const r = mk({ AWT_BIN: bin, AWT_TIMEOUT_MS: "20000" }, WS);
  const ac = new AbortController();
  const h = r.hooks.get("agent.open.before")!;
  const t0 = Date.now();
  const p = h(openReq("agt_1"), { paseo: {}, signal: ac.signal });
  setTimeout(() => ac.abort(), 200);
  const req = openReq("agt_1");
  assert.deepEqual(await p, req.request);
  assert.ok(Date.now() - t0 < 3000, `took ${Date.now() - t0} ms`);
});

test("C39 the harness env reaches every awt child", async () => {
  const tmp = mkdtempSync(join(tmpdir(), "awtenv-"));
  const bin = join(tmp, "fake-awt");
  writeFileSync(bin, `#!/bin/sh\necho "$HOME" >> "${tmp}/home"\nexit 1\n`);
  chmodSync(bin, 0o755);
  const r = mk({ AWT_BIN: bin }, WS);
  await r.call("agent.open.before", openReq("agt_1"));
  const homes = readFileSync(join(tmp, "home"), "utf8").trim().split("\n");
  assert.ok(homes.length >= 1);
  assert.deepEqual([...new Set(homes)], [r.tmp]);
});

test("C40 a node that moved while the daemon ran is found again", async () => {
  const r = mk({}, WS);
  const first = await r.call("agent.open.before", openReq("agt_1"));
  const moved = first.env.AWT_DIR.replace(/\/[^/]+$/, "/moved");
  renameSync(first.env.AWT_DIR, moved);
  const second = await r.call("agent.open.before", openReq("agt_1")); // path gone: cache dropped
  assert.equal(second.env.AWT_DIR, moved);
  // the old path comes back as a broken directory (.awt is a file): awt exits nonzero there, so the key is looked up again
  const again = join(moved, "..", "moved2");
  renameSync(moved, again);
  mkdirSync(moved);
  writeFileSync(join(moved, ".awt"), "x");
  await r.call("agent.archive.after", { agent: agentPayload("agt_1"), archivedAt: "x" });
  assert.equal(JSON.parse(r.awt(again, "resume", "--json")).status, "done");
});
