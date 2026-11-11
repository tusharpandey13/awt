import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { awt, parseJson } from "./awt";
import type { AwtConfig } from "./config";

export type Kind = "root" | "workspace" | "task" | "agent";

export interface NodeRow {
  path: string;
  kind: string;
  name: string;
  key: string | null;
  status: string;
  now: string | null;
  state_ts: string | null;
}

const clean = (s: string) => s.replace(/[\u0000-\u001f\u007f]+/g, " ").replace(/\s+/g, " ").trim();
const cut = (s: string, n: number) => (s.length <= n ? s : s.slice(0, n - 1).trimEnd() + "~");

export class Tree {
  private readonly keys = new Map<string, string>();
  private rootReady?: Promise<string>;

  constructor(readonly cfg: AwtConfig) {}

  /** Creates the root once per process. Idempotent on disk. */
  root(): Promise<string> {
    this.rootReady ??= (async () => {
      await mkdir(this.cfg.root, { recursive: true });
      const r = await awt(this.cfg, this.cfg.root, ["init", "--kind", "root"]);
      if (r.code !== 0) {
        this.rootReady = undefined;
        throw new Error(`awt init --kind root failed: ${r.stderr.trim().slice(0, 160)}`);
      }
      return this.cfg.root;
    })();
    return this.rootReady;
  }

  /** Finds or creates a child by key. A refused name (for example one that matches the secret scan) falls back to `fallback`. */
  async ensure(parent: string, kind: Exclude<Kind, "root">, name: string, key: string, opts: { goal?: string; done?: string; fallback?: string } = {}): Promise<string> {
    const cached = this.keys.get(key);
    if (cached) return cached;
    const attempt = async (label: string, goal: string | undefined) => {
      const args = ["init", "--kind", kind, "--name", cut(clean(label) || key, 60), "--key", key];
      const g = goal ?? (kind === "task" ? label : undefined);
      if (g) args.push("--goal", cut(clean(g) || "work", 250), "--done", cut(clean(opts.done ?? "done") || "done", 250));
      return awt(this.cfg, parent, args);
    };
    let r = await attempt(name, opts.goal);
    if (r.code !== 0 && opts.fallback) r = await attempt(opts.fallback, opts.fallback);
    const parts = r.stdout.trim().split(/\s+/);
    if (r.code !== 0 || parts[0] !== "init" || !parts[1]) throw new Error(`awt init ${kind} failed: ${r.stderr.trim().slice(0, 160)}`);
    const path = join(parent, parts[1]);
    this.keys.set(key, path);
    return path;
  }

  /** Finds a node by key anywhere in the tree. */
  async find(key: string): Promise<string | null> {
    const cached = this.keys.get(key);
    if (cached) return cached;
    const root = await this.root();
    const r = await awt(this.cfg, root, ["list", "nodes", "--all", "--json"]);
    for (const row of parseJson<NodeRow[]>(r.stdout, [])) {
      if (row.key) this.keys.set(row.key, join(root, row.path));
    }
    return this.keys.get(key) ?? null;
  }

  async ensureRefs(node: string, refs: { target: string; title: string; why?: string; noAccess?: boolean }[]): Promise<void> {
    const have = new Set(parseJson<{ target: string }[]>((await awt(this.cfg, node, ["list", "refs", "--json"])).stdout, []).map((r) => r.target));
    for (const ref of refs) {
      if (have.has(ref.target)) continue;
      const args = ["ref", ref.target, "--title", cut(clean(ref.title) || ref.target, 120)];
      if (ref.why) args.push("--why", cut(clean(ref.why), 200));
      if (ref.noAccess) args.push("--no-access");
      await awt(this.cfg, node, args);
    }
  }

  async status(node: string): Promise<string> {
    return parseJson<{ status?: string }>((await awt(this.cfg, node, ["resume", "--json"])).stdout, {}).status ?? "active";
  }

  async setStatusDoneOrPaused(node: string): Promise<"done" | "paused" | "unchanged"> {
    if ((await this.status(node)) === "done") return "unchanged";
    const done = await awt(this.cfg, node, ["status", "done"]);
    if (done.code === 0) return "done";
    const paused = await awt(this.cfg, node, ["status", "paused"]);
    return paused.code === 0 ? "paused" : "unchanged";
  }
}
