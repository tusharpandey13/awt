import { homedir } from "node:os";
import { join } from "node:path";

export interface AwtConfig {
  bin: string;
  root: string;
  timeoutMs: number;
  /** Send a follow-up prompt asking for a handoff. Off unless AWT_NUDGE=1. */
  nudge: boolean;
  /** At the end of a turn with no handoff, record the agent's last message as state in scope `auto`. On unless AWT_AUTO_HANDOFF=0. */
  autoHandoff: boolean;
  /** After each turn, a timeline row shows what awt stored: `on` (default), `changes` (only when something was stored) or `off` (AWT_RECEIPT=0 or off). */
  receipt: "on" | "changes" | "off";
  /** AWT_RELATED of the daemon, passed on to agents as it is (awt validates it). Empty or unset: not passed. */
  related: string | null;
  /** AWT_RECEIPT held a value other than 0, changes, on or empty. It is treated as on; the plugin logs one warning. */
  receiptBad: boolean;
  /** Paseo's `projects.json`, read only for `archivedAt` (the SDK has no project archive hook and `projects.list` carries no `archivedAt`). AWT_PASEO_PROJECTS overrides it; tests point it at a temp file. */
  projectsFile: string;
  /** The environment every awt child runs in. */
  env: NodeJS.ProcessEnv;
}

export function readConfig(env: NodeJS.ProcessEnv = process.env): AwtConfig {
  const data = env.XDG_DATA_HOME || join(homedir(), ".local", "share");
  const timeout = Number(env.AWT_TIMEOUT_MS);
  return {
    bin: env.AWT_BIN || "awt",
    root: env.AWT_ROOT || join(data, "awt"),
    timeoutMs: Number.isFinite(timeout) && timeout > 0 ? timeout : 5000,
    nudge: env.AWT_NUDGE === "1",
    autoHandoff: env.AWT_AUTO_HANDOFF !== "0",
    receipt: env.AWT_RECEIPT === "0" || env.AWT_RECEIPT === "off" ? "off" : env.AWT_RECEIPT === "changes" ? "changes" : "on",
    related: env.AWT_RELATED || null,
    receiptBad: !["", "0", "off", "1", "on", "changes", undefined].includes(env.AWT_RECEIPT),
    projectsFile: env.AWT_PASEO_PROJECTS || join(env.PASEO_HOME || join(env.HOME || homedir(), ".paseo"), "projects", "projects.json"),
    env,
  };
}
