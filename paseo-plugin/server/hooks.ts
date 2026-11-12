import { existsSync, realpathSync } from "node:fs";
import { basename, dirname, isAbsolute, join, resolve, sep } from "node:path";
import { createHash } from "node:crypto";
import { z } from "zod";
import { defineAgentTool } from "@getpaseo/plugin/server";
import type { PluginHookAgent, PluginHookContext, PluginServerContext } from "@getpaseo/plugin/server";
import { awt, parseJson, withSignal } from "./awt.js";
import type { AwtConfig } from "./config.js";
import { readConfig } from "./config.js";
import { NUDGE, withBlock } from "./prompt.js";
import { Tree, clean, cut } from "./tree.js";

/** The text of the last assistant message in a timeline page, wherever the page keeps its items. */
export function lastAssistantText(page: unknown): string | null {
  const found: { text: string; id?: string }[] = [];
  const walk = (v: unknown, depth: number): void => {
    if (depth > 6 || v === null || typeof v !== "object") return;
    if (Array.isArray(v)) return void v.forEach((x) => walk(x, depth + 1));
    const o = v as Record<string, unknown>;
    if (o.type === "assistant_message" && typeof o.text === "string" && (o.text.trim() || typeof o.messageId === "string")) found.push({ text: o.text, id: typeof o.messageId === "string" ? o.messageId : undefined });
    else Object.values(o).forEach((x) => walk(x, depth + 1));
  };
  walk(page, 0);
  const last = found[found.length - 1];
  if (!last) return null;
  // A streamed reply can arrive as several items with one messageId: join them.
  const text = last.id === undefined ? last.text : found.filter((f) => f.id === last.id).map((f) => f.text).join("");
  return text.trim() ? text : null;
}

type Log = (message: string) => void;

/** Paseo records a subagent's parent only as this label in 0.15.4; `parentAgentId` is absent there. */
const PARENT_LABEL = "paseo.parent-agent-id";
const parentFromLabels = (labels?: Readonly<Record<string, string>> | null): string | null => labels?.[PARENT_LABEL] || null;

/** Resolve a path through symlinks even when its tail does not exist yet (a file about to be written). */
function realish(p: string): string {
  let head = resolve(p);
  const tail: string[] = [];
  while (!existsSync(head) && dirname(head) !== head) {
    tail.unshift(basename(head));
    head = dirname(head);
  }
  return join(realpathSync(head), ...tail);
}

/** The paths a permission request wants, or null when it is not a kind we understand (then it is left alone). */
export function permissionTargets(req: { name: string; input?: Record<string, unknown>; detail?: { type?: string; filePath?: string } }): string[] | null {
  const detail = req.detail;
  if (detail && (detail.type === "write" || detail.type === "edit" || detail.type === "read") && typeof detail.filePath === "string") return [detail.filePath];
  if (req.name !== "external_directory") return null;
  const patterns = req.input?.patterns;
  if (!Array.isArray(patterns) || patterns.length === 0 || !patterns.every((x) => typeof x === "string")) return null;
  // opencode asks for a directory glob such as `<dir>/*`; only that trailing glob is understood.
  const dirs = (patterns as string[]).map((x) => x.replace(/\/\*{1,2}$/, ""));
  return dirs.every((d) => isAbsolute(d) && !/[*?[\]{}]/.test(d)) ? dirs : null;
}

/** True only when every target resolves, symlinks included, to the node dir itself or something inside it. */
export function insideNode(node: string, targets: string[]): boolean {
  let base: string;
  try {
    base = realpathSync(node);
  } catch {
    return false;
  }
  return targets.every((t) => {
    if (!isAbsolute(t)) return false;
    try {
      const r = realish(t);
      return r === base || r.startsWith(base + sep);
    } catch {
      return false;
    }
  });
}

const short = (id: string) => id.replace(/[^A-Za-z0-9]/g, "").slice(0, 8) || "agent";
const sha = (s: string) => createHash("sha1").update(s).digest("hex").slice(0, 16);

/** Every hook is wrapped: a failure is logged and the agent carries on without awt. */
async function safe<T>(log: Log, what: string, fallback: T, fn: () => Promise<T>): Promise<T> {
  try {
    return await fn();
  } catch (error) {
    log(`awt plugin: ${what} failed: ${error instanceof Error ? error.message : String(error)}`);
    return fallback;
  }
}

/**
 * One deadline for a whole waiting hook (`cfg.timeoutMs`, not per awt call). On expiry, or when the daemon cancels the hook,
 * the running awt children are killed and the request goes through unchanged.
 */
async function within<T>(cfg: AwtConfig, signal: AbortSignal | undefined, log: Log, what: string, fallback: T, fn: () => Promise<T>): Promise<T> {
  const ac = new AbortController();
  const cancel = () => ac.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  if (signal?.aborted) cancel();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<T>((resolve) => {
    timer = setTimeout(() => {
      log(`awt plugin: ${what} exceeded ${cfg.timeoutMs} ms; continuing without awt`);
      cancel();
      resolve(fallback);
    }, cfg.timeoutMs);
  });
  try {
    return await Promise.race([safe(log, what, fallback, () => withSignal(ac.signal, fn)), late]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
  }
}

export function registerHooks(server: Pick<PluginServerContext, "addHook">, env: NodeJS.ProcessEnv = process.env, log: Log = (m) => console.error(m)): () => void {
  const cfg = readConfig(env);
  const tree = new Tree(cfg, log);
  const turnStart = new Map<string, number>();
  /** Agents whose last open.before gave them an AWT_DIR. Only these are nudged. */
  const withDir = new Set<string>();
  /** When each agent was last nudged. It is nudged again only after it has recorded state since. */
  const nudgedAt = new Map<string, number>();
  /** Parent of each agent seen in open.before, whose request carries labels (the later hooks' agent payload may not). */
  const parents = new Map<string, string>();
  const parentOf = (a: { id: string; parentAgentId?: string | null; labels?: Readonly<Record<string, string>> | null }): string | null =>
    a.parentAgentId ?? parentFromLabels(a.labels) ?? parents.get(a.id) ?? null;

  const taskFor = async (workspaceNode: string, workspaceKeyPart: string): Promise<string> => {
    const pointer = parseJson<{ scope?: string; now?: string }[]>((await awt(cfg, workspaceNode, ["list", "state", "--json"])).stdout, []).find((s) => s.scope === "current-task");
    if (pointer?.now) {
      const found = await tree.find(pointer.now.trim());
      if (found) return found;
    }
    return tree.ensure(workspaceNode, "task", "main", `paseo:task/${workspaceKeyPart}/main`, { goal: "Work in this workspace", done: "ongoing" });
  };

  const workspaceNode = async (workspaceId: string | null, cwd: string, ctx?: PluginHookContext): Promise<{ node: string; part: string }> => {
    const root = await tree.root();
    if (workspaceId) {
      const key = `paseo:workspace/${workspaceId}`;
      const existing = await tree.find(key);
      if (existing) return { node: existing, part: workspaceId };
      let name: string | null = null;
      let dir = cwd;
      let projectId: string | null = null;
      try {
        const h = ctx?.paseo.workspaces.ref(workspaceId);
        await h?.refresh();
        name = h?.name ?? null;
        dir = h?.directory ?? cwd;
        projectId = h?.projectId ?? null;
      } catch {
        /* best effort */
      }
      return { node: await createWorkspace(root, workspaceId, name, dir, projectId, null), part: workspaceId };
    }
    const key = `paseo:unassigned/${sha(cwd)}`;
    const node = await tree.ensure(root, "workspace", `unassigned--${basename(cwd) || "root"}`, key, { goal: `unassigned--${basename(cwd) || "root"}`, done: "ongoing", fallback: "unassigned" });
    return { node, part: `unassigned-${sha(cwd)}` };
  };

  const createWorkspace = async (root: string, id: string, name: string | null, cwd: string, projectId: string | null, projectName: string | null): Promise<string> => {
    const label = `${projectName ?? (basename(cwd) || "workspace")}--${name ?? id}`;
    const node = await tree.ensure(root, "workspace", label, `paseo:workspace/${id}`, { goal: label, done: "ongoing", fallback: `workspace-${short(id)}` });
    await tree.ensureRefs(node, [
      ...(cwd ? [{ target: cwd, title: "working directory" }] : []),
      ...(projectId ? [{ target: `paseo:project/${projectId}`, title: projectName ?? "project" }] : []),
      { target: `paseo:workspace/${id}`, title: name ?? id },
    ]);
    return node;
  };

  const agentNode = async (agent: { id: string; workspaceId: string | null; cwd: string; title: string | null; provider?: string; parentAgentId?: string | null; labels?: Readonly<Record<string, string>> | null }, ctx?: PluginHookContext): Promise<string> => {
    const key = `paseo:agent/${agent.id}`;
    const existing = await tree.find(key);
    if (existing) return existing;
    if (tree.isDuplicate(key)) throw new Error(`key ${key} is carried by more than one node`);
    const ws = await workspaceNode(agent.workspaceId, agent.cwd, ctx);
    const parentId = parentOf(agent);
    let parent: string | null = parentId ? await tree.find(`paseo:agent/${parentId}`) : null;
    parent ??= await taskFor(ws.node, ws.part);
    const title = (agent.title ?? "").trim() || `agent-${short(agent.id)}`;
    const node = await tree.ensure(parent, "agent", title, key, { goal: title, done: "agent work recorded", fallback: `agent-${short(agent.id)}` });
    await tree.ensureRefs(node, [{ target: key, title, why: agent.provider }]);
    return node;
  };

  const awtResume = defineAgentTool({
    name: "awt_resume",
    title: "awt resume",
    description: "Print the awt brief for this agent's node: goal, lineage, rules, state, open questions. Call it first.",
    input: z.object({}),
    async execute(_input, context) {
      const r = await tree.onNode(`paseo:agent/${context.agent.id}`, (node) => awt(cfg, node, ["resume"], context.agent.id));
      if (!r) return { text: "No awt node for this agent yet.", isError: true };
      return r.code === 0 ? { text: r.stdout } : { text: r.stderr || "awt resume failed", isError: true };
    },
  });

  const removers: (() => void)[] = [];
  const add = (r: () => void) => removers.push(r);

  add(server.addHook("workspace.create.after", async ({ workspace }, ctx) => {
    await safe(log, "workspace.create.after", undefined, async () => {
      let projectName: string | null = null;
      try {
        const res = await ctx.paseo.projects.list();
        projectName = res.projects.find((p) => p.projectId === workspace.projectId)?.projectDisplayName ?? null;
      } catch {
        /* best effort */
      }
      const node = await createWorkspace(await tree.root(), workspace.id, workspace.name, workspace.cwd, workspace.projectId, projectName);
      await taskFor(node, workspace.id);
    });
  }));

  add(server.addHook("agent.create.before", async ({ request }, ctx) => {
    // The block tells the agent to use awt, so it goes in only when awt works.
    return within(cfg, ctx.signal, log, "agent.create.before", request, async () => {
      await tree.root();
      return { ...request, config: { ...request.config, systemPrompt: withBlock(request.config.systemPrompt) } };
    });
  }));

  add(server.addHook("agent.open.before", async ({ request }, ctx) => {
    if (request.purpose !== "interactive") return request;
    withDir.delete(request.agentId);
    const labelled = parentFromLabels(request.labels);
    if (labelled) parents.set(request.agentId, labelled);
    return within(cfg, ctx.signal, log, "agent.open.before", request, async () => {
      const node = await agentNode({ id: request.agentId, workspaceId: request.workspaceId, cwd: request.cwd, title: request.title, provider: request.provider, labels: request.labels }, ctx);
      withDir.add(request.agentId);
      return { ...request, env: { ...request.env, AWT_DIR: node, AWT_BY: request.agentId }, tools: [...request.tools.filter((t) => t.name !== "awt_resume"), awtResume] };
    });
  }));

  add(server.addHook("agent.create.after", async ({ agent }, ctx) => {
    await safe(log, "agent.create.after", undefined, async () => {
      const node = await agentNode(agent, ctx);
      const parentId = parentOf(agent);
      if (parentId) {
        const parent = await tree.find(`paseo:agent/${parentId}`);
        if (!parent) {
          await awt(cfg, node, ["note", `started by agent ${parentId}; it has no node, so this node is under the task`], agent.id);
        } else if (!node.startsWith(parent + "/")) {
          await awt(cfg, node, ["note", `started by agent ${parentId}; its node is ${parent}`], agent.id);
          await awt(cfg, node, ["ref", parent, "--title", "parent agent", "--kind", "node"], agent.id);
        }
      }
    });
  }));

  add(server.addHook("agent.turn.before", async ({ agent }) => {
    turnStart.set(agent.id, Date.now());
  }));

  add(server.addHook("agent.turn.after", async ({ agent, outcome }, ctx) => {
    await safe(log, "agent.turn.after", undefined, async () => {
      const started = turnStart.get(agent.id);
      turnStart.delete(agent.id);
      if (outcome.kind !== "completed" || parentOf(agent) || started === undefined || !withDir.has(agent.id)) return;
      if (!cfg.nudge && !cfg.autoHandoff) return;
      const r = await tree.onNode(`paseo:agent/${agent.id}`, (node) => awt(cfg, node, ["list", "state", "--all", "--json"], agent.id));
      if (!r) return;
      const rows = parseJson<{ ts?: string; scope?: string }[]>(r.stdout, []);
      const newest = (pick: (s: { scope?: string }) => boolean) =>
        rows.filter(pick).map((s) => Date.parse(s.ts ?? "")).filter(Number.isFinite).sort((x, y) => y - x)[0] ?? 0;
      const last = newest((s) => s.scope === "main" || s.scope === undefined);
      if (last >= started) return; // the agent recorded its own handoff this turn

      if (cfg.autoHandoff && !cfg.nudge) {
        // No message is sent into the chat. The agent's last reply stands in for the handoff, in a scope of its own,
        // so it never replaces a handoff the agent wrote and `resume` shows it next to one.
        const text = lastAssistantText(await ctx.paseo.agents.ref(agent.id).timeline.refetch({ direction: "tail", limit: 20 }));
        if (!text) return;
        await tree.onNode(`paseo:agent/${agent.id}`, (node) =>
          awt(cfg, node, ["state", "--scope", "auto", "--now", "[auto] " + cut(clean(text), 240), "--next", "not recorded: the agent ended its turn without a handoff"], "paseo-plugin"));
        return;
      }

      const before = nudgedAt.get(agent.id);
      if (before !== undefined && last < before) return; // nudged already, and nothing recorded since
      nudgedAt.set(agent.id, Date.now());
      try {
        await ctx.paseo.agents.ref(agent.id).send(NUDGE);
      } catch (error) {
        if (before === undefined) nudgedAt.delete(agent.id);
        else nudgedAt.set(agent.id, before);
        throw error;
      }
    });
  }));

  add(server.addHook("agent.archive.after", async ({ agent }) => {
    await safe(log, "agent.archive.after", undefined, async () => {
      await tree.onNode(`paseo:agent/${agent.id}`, (node) => tree.setStatusDoneOrPaused(node));
    });
  }));

  add(server.addHook("workspace.archive.after", async ({ workspace }) => {
    await safe(log, "workspace.archive.after", undefined, async () => {
      await tree.onNode(`paseo:workspace/${workspace.id}`, (node) => tree.setStatusDoneOrPaused(node));
    });
  }));

  // The one permission the plugin answers: an agent touching its own node dir, which is always outside its cwd. Anything else
  // (another node, AWT_ROOT, a symlink out, `..`, shell) is left for the person.
  add(server.addHook("agent.permission.before", async ({ agent, request }, ctx) => {
    await safe(log, "agent.permission.before", undefined, async () => {
      const targets = permissionTargets(request as Parameters<typeof permissionTargets>[0]);
      if (!targets) return;
      const node = await tree.find(`paseo:agent/${agent.id}`);
      if (!node || !insideNode(node, targets)) return;
      await ctx.paseo.agents.ref(agent.id).respondToPermission({ requestId: request.id, response: { behavior: "allow" } });
    });
  }));
  return () => removers.forEach((r) => r());
}

export type { PluginHookAgent };
