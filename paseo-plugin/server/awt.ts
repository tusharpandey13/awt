import { execFile } from "node:child_process";
import type { AwtConfig } from "./config";

export interface AwtResult {
  code: number;
  stdout: string;
  stderr: string;
}

/** Runs awt against one node. Never rejects: a missing binary, a timeout or a crash is a nonzero code. */
export function awt(cfg: AwtConfig, dir: string, args: string[], by = "paseo-plugin", env: NodeJS.ProcessEnv = process.env): Promise<AwtResult> {
  const childEnv: NodeJS.ProcessEnv = { ...env };
  delete childEnv.AWT_DIR;
  return new Promise((resolve) => {
    try {
      execFile(
        cfg.bin,
        ["--dir", dir, "--by", by, ...args],
        { timeout: cfg.timeoutMs, maxBuffer: 16 * 1024 * 1024, env: childEnv },
        (err, stdout, stderr) => {
          const code = err ? (typeof (err as NodeJS.ErrnoException & { code?: unknown }).code === "number" ? ((err as { code: number }).code) : -1) : 0;
          resolve({ code, stdout: String(stdout ?? ""), stderr: String(stderr ?? err?.message ?? "") });
        },
      );
    } catch (error) {
      resolve({ code: -1, stdout: "", stderr: String(error) });
    }
  });
}

export function parseJson<T>(text: string, fallback: T): T {
  try {
    return JSON.parse(text) as T;
  } catch {
    return fallback;
  }
}
