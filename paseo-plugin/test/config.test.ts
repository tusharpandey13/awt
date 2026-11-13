import assert from "node:assert/strict";
import { test } from "node:test";
import { homedir } from "node:os";
import { join } from "node:path";
import { readConfig } from "../server/config.js";

test("defaults: AWT_BIN awt, 5000 ms, root under XDG_DATA_HOME or ~/.local/share", () => {
  const c = readConfig({});
  assert.equal(c.bin, "awt");
  assert.equal(c.timeoutMs, 5000);
  assert.equal(c.root, join(homedir(), ".local", "share", "awt"));
  assert.equal(readConfig({ XDG_DATA_HOME: "/x/data" }).root, "/x/data/awt");
});

test("explicit settings win; a bad timeout falls back to 5000", () => {
  const c = readConfig({ AWT_BIN: "/b/awt", AWT_ROOT: "/r", AWT_TIMEOUT_MS: "1500" });
  assert.deepEqual([c.bin, c.root, c.timeoutMs], ["/b/awt", "/r", 1500]);
  for (const bad of ["0", "-3", "soon", ""]) assert.equal(readConfig({ AWT_TIMEOUT_MS: bad }).timeoutMs, 5000);
});

test("AWT_RECEIPT accepts off as well as 0; anything unknown is on and flagged", () => {
  for (const v of ["0", "off"]) assert.deepEqual([readConfig({ AWT_RECEIPT: v }).receipt, readConfig({ AWT_RECEIPT: v }).receiptBad], ["off", false]);
  assert.equal(readConfig({ AWT_RECEIPT: "changes" }).receipt, "changes");
  assert.equal(readConfig({}).receipt, "on");
  assert.deepEqual([readConfig({ AWT_RECEIPT: "sometimes" }).receipt, readConfig({ AWT_RECEIPT: "sometimes" }).receiptBad], ["on", true]);
});
