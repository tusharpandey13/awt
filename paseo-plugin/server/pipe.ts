import { execFile } from "node:child_process";
import { appendFileSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
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
 * Sends the events of Paseo's lifecycle hooks to `awt ingest --source paseo --stdin`, in batches and never awaited by a hook.
 * Every event is also appended to a spool file (`<store>/ingest/paseo.spool.jsonl`, mode 600) when it is queued, and leaves it only after a send that exited 0.
 * So a crash, a daemon restart or a failed send loses nothing: the leftover events are sent again at the next flush or at start (the event id makes a resend add nothing).
 * `AWT_PIPE=0` turns it off; `AWT_PIPE_DELAY_MS` (default 3000) is how long permission events wait for company before a batch is sent.
 * A turn event sends its batch at once, so a turn costs one ingest.
 */
export class Pipe {
  private queue: PipeEvent[] = [];
  private timer: ReturnType<typeof setTimeout> | undefined;
  private sending: Promise<void> | undefined;
  private again = false;
  readonly on: boolean;
  private readonly delay: number;
  private readonly spoolPath: string;

  constructor(private cfg: AwtConfig, private log: Log) {
    this.on = cfg.env.AWT_PIPE !== "0";
    const d = Number(cfg.env.AWT_PIPE_DELAY_MS);
    this.delay = Number.isFinite(d) && d >= 0 ? d : 3000;
    this.spoolPath = join(cfg.store, "ingest", "paseo.spool.jsonl");
    if (!this.on) return;
    try {
      for (const line of readFileSync(this.spoolPath, "utf8").split("\n")) {
        try {
          const e = JSON.parse(line);
          if (e && typeof e.eid === "string" && !this.queue.some((q) => q.eid === e.eid)) this.queue.push(e);
        } catch {} // a torn line
      }
    } catch {} // no spool
    if (this.queue.length) this.later();
  }

  private later(): void {
    this.timer ??= setTimeout(() => this.flush(), this.delay);
    this.timer.unref?.();
  }

  /** Queues an event and spools it. `now` sends the batch at once; otherwise it goes after the delay. */
  add(event: PipeEvent, now = false): void {
    if (!this.on) return;
    this.queue.push(event);
    try {
      mkdirSync(dirname(this.spoolPath), { recursive: true, mode: 0o700 });
      appendFileSync(this.spoolPath, JSON.stringify(event) + "\n", { mode: 0o600 });
    } catch (error) {
      this.log(`awt plugin: pipe spool failed (events stay in memory only): ${String(error)}`);
    }
    if (now) return this.flush();
    this.later();
  }

  flush(): void {
    clearTimeout(this.timer);
    this.timer = undefined;
    if (this.sending) {
      this.again = true; // the batch in flight is not final: send what was queued since once it ends
      return;
    }
    const batch = [...this.queue];
    if (!batch.length) return;
    this.sending = this.send(batch)
      .then((ok) => void (ok && this.acknowledge(batch)))
      .finally(() => {
        this.sending = undefined;
        if (this.again) {
          this.again = false;
          this.flush();
        }
      });
  }

  /** Resolves when every batch sent so far has finished. For tests and shutdown. */
  async idle(): Promise<void> {
    this.flush();
    while (this.sending) await this.sending;
  }

  /** Drops delivered events from memory and from the spool. */
  private acknowledge(batch: PipeEvent[]): void {
    const done = new Set(batch.map((e) => e.eid));
    this.queue = this.queue.filter((e) => !done.has(e.eid));
    try {
      if (!this.queue.length) return rmSync(this.spoolPath, { force: true });
      const tmp = `${this.spoolPath}.${process.pid}.tmp`;
      writeFileSync(tmp, this.queue.map((e) => JSON.stringify(e) + "\n").join(""), { mode: 0o600 });
      renameSync(tmp, this.spoolPath);
    } catch (error) {
      this.log(`awt plugin: pipe spool not updated: ${String(error)}`); // the events are sent again later; the event id makes that harmless
    }
  }

  /** True when awt took the batch (exit 0). */
  private send(batch: PipeEvent[]): Promise<boolean> {
    const env: NodeJS.ProcessEnv = { ...this.cfg.env };
    delete env.AWT_DIR;
    return new Promise((resolve) => {
      try {
        const child = execFile(this.cfg.bin, ["--dir", this.cfg.root, "ingest", "--source", "paseo", "--stdin"], { timeout: Math.max(this.cfg.timeoutMs, 120_000), env }, (err, _out, stderr) => {
          if (err) this.log(`awt plugin: pipe of ${batch.length} events failed (kept, sent again later): ${String(stderr || err.message).trim().slice(0, 300)}`);
          resolve(!err);
        });
        child.stdin?.on("error", () => {}); // a child that died before reading is reported by the callback
        child.stdin?.end(batch.map((e) => JSON.stringify(e)).join("\n") + "\n");
      } catch (error) {
        this.log(`awt plugin: pipe failed: ${String(error)}`);
        resolve(false);
      }
    });
  }
}
