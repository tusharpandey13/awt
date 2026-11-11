import { homedir } from "node:os";
import { join } from "node:path";

export interface AwtConfig {
  bin: string;
  root: string;
  timeoutMs: number;
}

export function readConfig(env: NodeJS.ProcessEnv = process.env): AwtConfig {
  const data = env.XDG_DATA_HOME || join(homedir(), ".local", "share");
  const timeout = Number(env.AWT_TIMEOUT_MS);
  return {
    bin: env.AWT_BIN || "awt",
    root: env.AWT_ROOT || join(data, "awt"),
    timeoutMs: Number.isFinite(timeout) && timeout > 0 ? timeout : 5000,
  };
}
