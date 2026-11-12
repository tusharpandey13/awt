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
    env,
  };
}
