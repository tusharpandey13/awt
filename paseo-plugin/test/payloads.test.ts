// P11: recorded hook payloads (fictional parsekit data, shaped like Paseo 0.15.4 requests) are type-checked against the
// installed @getpaseo/plugin types, then fed through the real hooks. A Paseo upgrade that changes a shape fails here.
import assert from "node:assert/strict";
import { test, afterEach } from "node:test";
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { rig, type Rig } from "./harness.js";

const DIR = join(import.meta.dirname, "payloads");
const PLUGIN = join(import.meta.dirname, "..");
const names = () => readdirSync(DIR).filter((f) => f.endsWith(".json")).map((f) => f.slice(0, -5)).sort();
const load = (n: string): any => JSON.parse(readFileSync(join(DIR, n + ".json"), "utf8"));
const WS = { "3f9c1a52-7b1e-4d0a-9a55-0c2d5e8a1b01": { name: "main", directory: "/tmp/parsekit", projectId: "prj-parsekit" } };

const rigs: Rig[] = [];
afterEach(() => rigs.splice(0).forEach((r) => r.cleanup()));

/** tsc over a generated file that assigns each payload to PluginHookPayload<hook>. Returns tsc's output, "" when clean. */
function tscCheck(entries: [string, unknown][]): string {
  const file = join(DIR, `_check-${process.pid}.gen.ts`);
  const src = 'import type { PluginHookPayload } from "@getpaseo/plugin/server";\n' +
    entries.map(([n, p], i) => `export const p${i}: PluginHookPayload<${JSON.stringify(n)}> = ${JSON.stringify(p)};\n`).join("");
  writeFileSync(file, src);
  try {
    execFileSync(join(PLUGIN, "node_modules", ".bin", "tsc"), ["--noEmit", "--strict", "--skipLibCheck", "--target", "ES2020", "--module", "ESNext", "--moduleResolution", "Bundler", "--types", "node", file], { cwd: PLUGIN, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
    return "";
  } catch (e: any) {
    return String(e.stdout ?? "") + String(e.stderr ?? "") || String(e);
  } finally {
    rmSync(file, { force: true });
  }
}

test("P11 there is one recorded payload for every hook the plugin registers", () => {
  const r = rig();
  rigs.push(r);
  assert.deepEqual(names(), [...r.hooks.keys()].sort());
});

test("P11 every recorded payload type-checks against the installed @getpaseo/plugin", () => {
  const out = tscCheck(names().map((n) => [n, load(n)]));
  assert.equal(out, "");
  // The check must be able to fail: a payload with a wrong shape is rejected.
  const bad = tscCheck([["agent.turn.after", { ...load("agent.turn.after"), outcome: { kind: "finished" } }]]);
  assert.match(bad, /error TS/);
});

test("P11 the recorded payloads drive the hooks end to end", async () => {
  const r = rig({}, WS);
  rigs.push(r);
  const agentId = load("agent.create.after").agent.id;
  const wsId = load("workspace.create.after").workspace.id;
  const call = (n: string, p: unknown = load(n)) => r.call(n, p);

  await call("workspace.create.after");
  const before = await call("agent.create.before");
  assert.match(before.config.systemPrompt, /^You work on parsekit\./);
  assert.equal(before.env.PARSEKIT_ENV, "dev");

  const open = await call("agent.open.before");
  assert.equal(open.env.AWT_BY, agentId);
  assert.equal(open.env.PARSEKIT_ENV, "dev");
  const dir: string = open.env.AWT_DIR;
  assert.match(dir, /\/agents\/fix-parsekit-tokenizer$/);
  assert.deepEqual(open.tools.map((t: any) => t.name), ["awt_resume"]);

  await call("agent.create.after");
  await call("agent.turn.before");
  await call("agent.turn.after");
  assert.equal(r.sent.length, 1); // no handoff recorded: nudged once

  const perm = JSON.parse(JSON.stringify(load("agent.permission.before")).replaceAll("{{AWT_DIR}}", dir));
  await call("agent.permission.before", perm);
  assert.deepEqual(r.answered, [{ id: agentId, requestId: "perm-0001", behavior: "allow" }]);

  await call("agent.archive.after");
  await call("workspace.archive.after");
  const n = r.nodes();
  assert.equal(n.find((x) => x.key === `paseo:agent/${agentId}`)!.status, "done");
  assert.ok(n.find((x) => x.key === `paseo:workspace/${wsId}`));
  assert.deepEqual(r.logs, []);
});
