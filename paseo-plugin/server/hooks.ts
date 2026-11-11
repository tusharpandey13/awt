import { basename } from "node:path";
import { createHash } from "node:crypto";
import { z } from "zod";
import { defineAgentTool } from "@getpaseo/plugin/server";
import type { PluginHookAgent, PluginHookContext, PluginServerContext } from "@getpaseo/plugin/server";
import { awt, parseJson } from "./awt";
import { readConfig } from "./config";
import { NUDGE, withBlock } from "./prompt";
import { Tree } from "./tree";

type Log = (message: string) => void;

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

export function registerHooks(server: Pick<PluginServerContext, "addHook">, env: NodeJS.ProcessEnv = process.env, log: Log = (m) => console.error(m)): () => void {
  const cfg = readConfig(env);
  const tree = new Tree(cfg);
  const turnStart = new Map<string, number>();
  const nudged = new Set<string>();

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

  const agentNode = async (agent: { id: string; workspaceId: string | null; cwd: string; title: string | null; provider?: string; parentAgentId?: string | null }, ctx?: PluginHookContext): Promise<string> => {
    const key = `paseo:agent/${agent.id}`;
    const existing = await tree.find(key);
    if (existing) return existing;
    const ws = await workspaceNode(agent.workspaceId, agent.cwd, ctx);
    let parent: string | null = agent.parentAgentId ? await tree.find(`paseo:agent/${agent.parentAgentId}`) : null;
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
      const node = await tree.find(`paseo:agent/${context.agent.id}`);
      if (!node) return { text: "No awt node for this agent yet.", isError: true };
      const r = await awt(cfg, node, ["resume"], context.agent.id);
      return r.code === 0 ? { text: r.stdout } : { text: r.stderr || "awt resume failed", isError: true };
    },
  });

  const removers: (() => void)[] = [];
  const add = (r: () => void) => removers.push(r);

  add(server.addHook("workspace.create.after", async ({ workspace }, ctx) => {
    await safe(log, "workspace.create.after", undefined, async () => {
      let projectName: string | null = null;
      try {
        const projects = await ctx.paseo.projects.list();
        projectName = (projects as unknown as { projects?: { id?: string; projectId?: string; name?: string }[] }).projects?.find((p) => (p.id ?? p.projectId) === workspace.projectId)?.name ?? null;
      } catch {
        /* best effort */
      }
      const node = await createWorkspace(await tree.root(), workspace.id, workspace.name, workspace.cwd, workspace.projectId, projectName);
      await taskFor(node, workspace.id);
    });
  }));

  add(server.addHook("agent.create.before", async ({ request }) => {
    return safe(log, "agent.create.before", request, async () => ({
      ...request,
      config: { ...request.config, systemPrompt: withBlock(request.config.systemPrompt) },
    }));
  }));

  add(server.addHook("agent.open.before", async ({ request }, ctx) => {
    if (request.purpose !== "interactive") return request;
    return safe(log, "agent.open.before", request, async () => {
      const node = await agentNode({ id: request.agentId, workspaceId: request.workspaceId, cwd: request.cwd, title: request.title, provider: request.provider }, ctx);
      return { ...request, env: { ...request.env, AWT_DIR: node, AWT_BY: request.agentId }, tools: [...request.tools.filter((t) => t.name !== "awt_resume"), awtResume] };
    });
  }));

  add(server.addHook("agent.create.after", async ({ agent }, ctx) => {
    await safe(log, "agent.create.after", undefined, async () => {
      const node = await agentNode(agent, ctx);
      if (agent.parentAgentId) {
        const parent = await tree.find(`paseo:agent/${agent.parentAgentId}`);
        if (parent && !node.startsWith(parent + "/")) {
          await awt(cfg, node, ["note", `started by agent ${agent.parentAgentId}; its node is ${parent}`], agent.id);
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
      if (nudged.delete(agent.id)) return; // the turn that answered our nudge never triggers another
      if (outcome.kind !== "completed" || agent.parentAgentId || started === undefined) return;
      const node = await tree.find(`paseo:agent/${agent.id}`);
      if (!node) return;
      const states = parseJson<{ ts?: string }[]>((await awt(cfg, node, ["list", "state", "--all", "--json"], agent.id)).stdout, []);
      const last = states.map((s) => Date.parse(s.ts ?? "")).filter(Number.isFinite).sort((a, b) => b - a)[0] ?? 0;
      if (last >= started) return;
      nudged.add(agent.id);
      try {
        await ctx.paseo.agents.ref(agent.id).send(NUDGE);
      } catch (error) {
        nudged.delete(agent.id);
        throw error;
      }
    });
  }));

  add(server.addHook("agent.archive.after", async ({ agent }) => {
    await safe(log, "agent.archive.after", undefined, async () => {
      const node = await tree.find(`paseo:agent/${agent.id}`);
      if (node) await tree.setStatusDoneOrPaused(node);
    });
  }));

  add(server.addHook("workspace.archive.after", async ({ workspace }) => {
    await safe(log, "workspace.archive.after", undefined, async () => {
      const node = await tree.find(`paseo:workspace/${workspace.id}`);
      if (node) await tree.setStatusDoneOrPaused(node);
    });
  }));

  // No agent.permission.* hook on purpose: the plugin never answers a permission request.
  return () => removers.forEach((r) => r());
}

export type { PluginHookAgent };
