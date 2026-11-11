import { existsSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { awt, parseJson, type AwtResult } from "./awt.js";
import type { AwtConfig } from "./config.js";

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
  /** Keys that more than one node carries. They resolve to nothing, so no agent is steered to a node it may not own. */
  private duplicated = new Set<string>();
  private rootReady?: Promise<string>;

  constructor(readonly cfg: AwtConfig, private readonly log: (message: string) => void = () => {}) {}

  /** Creates the root once per process. Idempotent on disk. */
  root(): Promise<string> {
    this.rootReady ??= (async () => {
      await mkdir(this.cfg.root, { recursive: true });
      const r = await awt(this.cfg, this.cfg.root, ["init", "--kind", "root"]);
      if (r.code !== 0 || r.stdout.trim().split(/\s+/)[0] !== "init") {
        this.rootReady = undefined;
        throw new Error(`awt init --kind root failed: ${r.stderr.trim().slice(0, 160)}`);
      }
      return this.cfg.root;
    })();
    return this.rootReady;
  }

  /** Finds or creates a child by key. A refused name (for example one that matches the secret scan) falls back to `fallback`. */
  async ensure(parent: string, kind: Exclude<Kind, "root">, name: string, key: string, opts: { goal?: string; done?: string; fallback?: string } = {}): Promise<string> {
    const cached = this.cached(key);
    if (cached) return cached;
    if (this.duplicated.has(key)) throw new Error(`key ${key} is carried by more than one node`);
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

  /** A cached path, dropped when the node is gone from disk. */
  private cached(key: string): string | undefined {
    const path = this.keys.get(key);
    if (path && !existsSync(join(path, ".awt"))) {
      this.keys.delete(key);
      return undefined;
    }
    return path;
  }

  /** Finds a node by key anywhere in the tree. A key carried by more than one node is an error: logged, and null. */
  async find(key: string): Promise<string | null> {
    const cached = this.cached(key);
    if (cached) return cached;
    const root = await this.root();
    const r = await awt(this.cfg, root, ["list", "nodes", "--all", "--json"]);
    const seen = new Map<string, string>();
    const dups = new Set<string>();
    for (const row of parseJson<NodeRow[]>(r.stdout, [])) {
      if (!row.key) continue;
      if (seen.has(row.key)) dups.add(row.key);
      else seen.set(row.key, join(root, row.path));
    }
    for (const k of dups) if (!this.duplicated.has(k)) this.log(`awt plugin: key ${k} is carried by more than one node; ignoring it`);
    this.duplicated = dups;
    for (const [k, path] of seen) if (!dups.has(k)) this.keys.set(k, path);
    for (const k of dups) this.keys.delete(k);
    return this.keys.get(key) ?? null;
  }

  /** True when the last lookup found `key` on more than one node. */
  isDuplicate(key: string): boolean {
    return this.duplicated.has(key);
  }

  /** Runs `fn` on the node for `key`. A nonzero exit drops the cached path and retries once on a fresh lookup. */
  async onNode(key: string, fn: (node: string) => Promise<AwtResult>): Promise<AwtResult | null> {
    const node = await this.find(key);
    if (!node) return null;
    const r = await fn(node);
    if (r.code === 0) return r;
    this.keys.delete(key);
    const again = await this.find(key);
    return again && again !== node ? fn(again) : r;
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

  async setStatusDoneOrPaused(node: string): Promise<AwtResult> {
    const current = parseJson<{ status?: string }>((await awt(this.cfg, node, ["resume", "--json"])).stdout, {}).status;
    if (current === "done") return { code: 0, stdout: "", stderr: "" };
    const done = await awt(this.cfg, node, ["status", "done"]);
    return done.code === 0 ? done : awt(this.cfg, node, ["status", "paused"]);
  }
}
