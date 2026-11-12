import { mkdtempSync, realpathSync, rmSync, readFileSync, existsSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { execFileSync } from "node:child_process";
import type { PaseoApi } from "@getpaseo/client";
import { registerHooks } from "../server/hooks.js";

export const AWT = resolve(import.meta.dirname, "..", "..", "awt");

type Handler = (payload: any, ctx: any) => Promise<any>;

export interface Rig {
  tmp: string;
  root: string;
  logs: string[];
  sent: { id: string; text: string }[];
  /** What the fake daemon's timeline returns for an agent: its assistant messages, oldest first. */
  said: Map<string, string[]>;
  answered: { id: string; requestId: string; behavior: string }[];
  /** Plugin timeline rows appended through `agents.ref(id).timeline.append`. Set `failAppend` to make the append throw. */
  appended: { id: string; item: { type: string; id?: string; kind: string; version: number; data: any } }[];
  failAppend: { on: boolean };
  call(name: string, payload: unknown): Promise<any>;
  hooks: Map<string, Handler>;
  /** A new plugin process on the same tree: empty caches. */
  restart(): void;
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
  const said = new Map<string, string[]>();
  const answered: { id: string; requestId: string; behavior: string }[] = [];
  const appended: Rig["appended"] = [];
  const failAppend = { on: false };
  const start = () => registerHooks({ addHook: (name: string, fn: Handler) => (hooks.set(name, fn), () => hooks.delete(name)) } as any, env, (m) => logs.push(m));
  start();
  // Typed against the SDK, so a mock cannot drift from the real shapes.
  const project: Awaited<ReturnType<PaseoApi["projects"]["list"]>>["projects"][number] = { projectId: "prj_1", projectDisplayName: "parsekit", projectRootPath: "/tmp/parsekit", projectKind: "git" };
  const paseo = {
    workspaces: {
      // Only the members the plugin reads; the cast is confined to the handle's extra members.
      ref: (id: string) => {
        const h: Pick<ReturnType<PaseoApi["workspaces"]["ref"]>, "name" | "directory" | "projectId" | "refresh"> = {
          name: workspaces[id]?.name ?? null,
          directory: workspaces[id]?.directory ?? null,
          projectId: workspaces[id]?.projectId ?? null,
          refresh: async () => null,
        };
        return h as ReturnType<PaseoApi["workspaces"]["ref"]>;
      },
    },
    projects: { list: async () => ({ requestId: "r1", projects: [project] }) },
    agents: { ref: (id: string) => ({ timeline: { append: async (item: Rig["appended"][number]["item"]) => { if (failAppend.on) throw new Error("append refused"); appended.push({ id, item }); return { ok: true }; }, refetch: async () => ({ entries: (said.get(id) ?? []).map((text) => ({ item: { type: "assistant_message", text } })) }) }, send: async (text: string) => void sent.push({ id, text }), respondToPermission: async (o: { requestId: string; response: { behavior: string } }) => void answered.push({ id, requestId: o.requestId, behavior: o.response.behavior }) }) as unknown as ReturnType<PaseoApi["agents"]["ref"]> },
  } satisfies Partial<{ [K in keyof PaseoApi]: Partial<PaseoApi[K]> }>;
  const ctx = { paseo, signal: new AbortController().signal };
  const run = (dir: string, args: string[]) => execFileSync(AWT, ["--dir", dir, ...args], { env, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  return {
    tmp, root, logs, sent, said, answered, appended, failAppend, hooks,
    restart: () => (hooks.clear(), void start()),
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
