import { mkdtempSync, realpathSync, rmSync, readFileSync, existsSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { execFileSync } from "node:child_process";
import { registerHooks } from "../server/hooks";

export const AWT = resolve(import.meta.dirname, "..", "..", "awt");

type Handler = (payload: any, ctx: any) => Promise<any>;

export interface Rig {
  tmp: string;
  root: string;
  logs: string[];
  sent: { id: string; text: string }[];
  call(name: string, payload: unknown): Promise<any>;
  hooks: Map<string, Handler>;
  awt(dir: string, ...args: string[]): string;
  nodes(): { path: string; kind: string; name: string; key: string | null; status: string }[];
  rows(node: string, type?: string): any[];
  cleanup(): void;
}

export function rig(extraEnv: Record<string, string> = {}, workspaces: Record<string, { name: string; directory: string; projectId: string }> = {}): Rig {
  const tmp = realpathSync(mkdtempSync(join(tmpdir(), "awtplug-")));
  const root = join(tmp, "root");
  const env = { ...process.env, HOME: tmp, AWT_BIN: AWT, AWT_ROOT: root, AWT_TIMEOUT_MS: "20000", GIT_CONFIG_GLOBAL: "/dev/null", ...extraEnv };
  const hooks = new Map<string, Handler>();
  const logs: string[] = [];
  const sent: { id: string; text: string }[] = [];
  registerHooks({ addHook: (name: string, fn: Handler) => (hooks.set(name, fn), () => hooks.delete(name)) } as any, env, (m) => logs.push(m));
  const paseo = {
    workspaces: { ref: (id: string) => ({ ...(workspaces[id] ?? { name: null, directory: null, projectId: null }), refresh: async () => {} }) },
    projects: { list: async () => ({ projects: [{ id: "prj_1", name: "parsekit" }] }) },
    agents: { ref: (id: string) => ({ send: async (text: string) => void sent.push({ id, text }) }) },
  };
  const ctx = { paseo, signal: new AbortController().signal };
  const run = (dir: string, args: string[]) => execFileSync(AWT, ["--dir", dir, ...args], { env, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  return {
    tmp, root, logs, sent, hooks,
    call: async (name, payload) => {
      const h = hooks.get(name);
      if (!h) throw new Error("no hook " + name);
      return h(payload, ctx);
    },
    awt: (dir, ...args) => run(dir, args),
    nodes: () => (existsSync(join(root, ".awt")) ? JSON.parse(run(root, ["list", "nodes", "--all", "--json"])) : []),
    rows: (node, type) => readFileSync(join(node, ".awt", "events.jsonl"), "utf8").split("\n").filter((l) => l.startsWith("{")).map((l) => JSON.parse(l)).filter((r) => !type || r.type === type),
    cleanup: () => rmSync(tmp, { recursive: true, force: true }),
  };
}

export const openReq = (agentId: string, over: Record<string, unknown> = {}) => ({
  request: { agentId, workspaceId: "wks_1", provider: "claude", cwd: "/tmp/parsekit", reason: "create", purpose: "interactive", title: `Chat ${agentId}`, labels: {}, tools: [], env: { KEEP: "1" }, mcpServers: {}, ...over },
});

export const agentPayload = (id: string, over: Record<string, unknown> = {}) => ({
  id, workspaceId: "wks_1", parentAgentId: null, provider: "claude", cwd: "/tmp/parsekit", title: `Chat ${id}`, ...over,
});

export const exists = existsSync;
export const ls = readdirSync;
