import { execFile } from "node:child_process";
import type { AwtConfig } from "./config.js";

/** One line of the Paseo pipe (SPEC.md, `awt ingest --source paseo --stdin`). Values are strings; absent ones are left out. */
export interface PipeEvent {
  event: "turn" | "permission" | "permission_resolved";
  eid: string;
  agentId: string;
  [key: string]: string | undefined;
}

type Log = (message: string) => void;

/**
 * Sends the events of Paseo's lifecycle hooks to `awt ingest --source paseo --stdin`, in batches and never awaited by a hook:
 * a failure is logged and the events of that batch are lost to the store (the next batch is unaffected).
 * `AWT_PIPE=0` turns it off; `AWT_PIPE_DELAY_MS` (default 3000) is how long permission events wait for company before a batch is sent.
 * A turn event sends its batch at once, so a turn costs one ingest.
 */
export class Pipe {
  private queue: PipeEvent[] = [];
  private timer: ReturnType<typeof setTimeout> | undefined;
  private inflight = new Set<Promise<void>>();
  readonly on: boolean;
  private readonly delay: number;

  constructor(private cfg: AwtConfig, private log: Log) {
    this.on = cfg.env.AWT_PIPE !== "0";
    const d = Number(cfg.env.AWT_PIPE_DELAY_MS);
    this.delay = Number.isFinite(d) && d >= 0 ? d : 3000;
  }

  /** Queues an event. `now` sends the batch at once; otherwise it goes after the delay. */
  add(event: PipeEvent, now = false): void {
    if (!this.on) return;
    this.queue.push(event);
    if (now) return this.flush();
    this.timer ??= setTimeout(() => this.flush(), this.delay);
    this.timer.unref?.();
  }

  /** Registers work that will `add` an event, so `idle` waits for it. */
  track(work: Promise<void>): void {
    const p = work.finally(() => this.inflight.delete(p));
    this.inflight.add(p);
  }

  flush(): void {
    clearTimeout(this.timer);
    this.timer = undefined;
    const batch = this.queue.splice(0);
    if (!batch.length) return;
    const p = this.send(batch).finally(() => this.inflight.delete(p));
    this.inflight.add(p);
  }

  /** Resolves when every batch sent so far has finished. For tests and shutdown. */
  async idle(): Promise<void> {
    this.flush();
    while (this.inflight.size) await Promise.all([...this.inflight]);
  }

  private send(batch: PipeEvent[]): Promise<void> {
    const env: NodeJS.ProcessEnv = { ...this.cfg.env };
    delete env.AWT_DIR;
    return new Promise((resolve) => {
      try {
        const child = execFile(this.cfg.bin, ["--dir", this.cfg.root, "ingest", "--source", "paseo", "--stdin"], { timeout: Math.max(this.cfg.timeoutMs, 120_000), env }, (err, _out, stderr) => {
          if (err) this.log(`awt plugin: pipe of ${batch.length} events failed: ${String(stderr || err.message).trim().slice(0, 300)}`);
          resolve();
        });
        child.stdin?.on("error", () => {}); // a child that died before reading is reported by the callback
        child.stdin?.end(batch.map((e) => JSON.stringify(e)).join("\n") + "\n");
      } catch (error) {
        this.log(`awt plugin: pipe failed: ${String(error)}`);
        resolve();
      }
    });
  }
}
