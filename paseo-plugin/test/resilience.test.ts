import assert from "node:assert/strict";
import { test, afterEach } from "node:test";
import { chmodSync, mkdtempSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { agentPayload, openReq, rig, type Rig } from "./harness";

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

test("C30 hook storm: 40 agents, each opened twice at once, no duplicates", async () => {
  const r = mk({}, WS);
  const ids = Array.from({ length: 40 }, (_, i) => `agt_${i}`);
  const outs = await Promise.all([...ids, ...ids].map((id) => r.call("agent.open.before", openReq(id))));
  const nodes = r.nodes();
  const keys = nodes.map((n) => n.key);
  assert.equal(new Set(keys).size, keys.length);
  assert.equal(nodes.filter((n) => n.kind === "agent").length, 40);
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
    assert.match(created.config.systemPrompt, /\[awt\]/); // the prompt block needs no awt
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

test("C34 an agent that never records state is nudged once, not in a loop", async () => {
  const r = mk({}, WS);
  await r.call("agent.open.before", openReq("agt_1"));
  for (let i = 0; i < 6; i++) {
    await r.call("agent.turn.before", { agent: agentPayload("agt_1"), turnId: `t${i}` });
    await r.call("agent.turn.after", { agent: agentPayload("agt_1"), turnId: `t${i}`, outcome: { kind: "completed" }, timeline: [] });
  }
  // nudge on t0, skip t1 (the answer), nudge on t2, skip t3, ...: never two in a row
  assert.equal(r.sent.length, 3);
});
