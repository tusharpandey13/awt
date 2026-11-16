/** Detected effects (SPEC, Effects, Detected). The plugin only reports tool calls to `awt ingest --event`; awt labels them and keeps the ledger. Nothing here denies or runs anything. */

export interface DetectEvent {
  phase: "before" | "after" | "denied";
  tool: string;
  input: Record<string, unknown>;
  cwd?: string;
  id?: string;
  ok?: boolean | null;
}

type AgentLike = { cwd?: string | null };

const isObj = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);

/**
 * The event for a permission request, or null when it is not a call awt could label. A shell request carries `detail.type === "shell"`
 * (Claude Code, opencode 1.x, ACP). An opencode 2.x request has no `input` and no `detail`, so it is null here and the turn scan sees the call later.
 */
export function permissionEvent(agent: AgentLike, request: unknown): DetectEvent | null {
  if (!isObj(request) || typeof request.id !== "string") return null;
  const detail = isObj(request.detail) ? request.detail : null;
  const cwd = (detail && typeof detail.cwd === "string" ? detail.cwd : undefined) ?? agent.cwd ?? undefined;
  if (detail?.type === "shell" && typeof detail.command === "string") return { phase: "before", tool: "Bash", input: { command: detail.command }, cwd, id: request.id };
  if (typeof request.name === "string" && request.name.startsWith("mcp__") && isObj(request.input)) return { phase: "before", tool: request.name, input: request.input, cwd, id: request.id };
  return null;
}

/** Every finished shell or MCP tool call in a timeline page, wherever the page keeps its items. Running calls are left for a later turn. */
export function callEvents(page: unknown, agent: AgentLike): DetectEvent[] {
  const found: DetectEvent[] = [];
  const walk = (v: unknown, depth: number): void => {
    if (depth > 6 || v === null || typeof v !== "object") return;
    if (Array.isArray(v)) return void v.forEach((x) => walk(x, depth + 1));
    const o = v as Record<string, unknown>;
    if (o.type !== "tool_call") return void Object.values(o).forEach((x) => walk(x, depth + 1));
    if (typeof o.callId !== "string" || o.status === "running" || typeof o.name !== "string") return;
    const detail = isObj(o.detail) ? o.detail : {};
    const cwd = (typeof detail.cwd === "string" ? detail.cwd : undefined) ?? agent.cwd ?? undefined;
    const ok = o.status === "completed" ? (detail.exitCode === undefined || detail.exitCode === null || detail.exitCode === 0) : o.status === "failed" ? false : null;
    if (detail.type === "shell" && typeof detail.command === "string") found.push({ phase: "after", tool: "Bash", input: { command: detail.command }, cwd, id: o.callId, ok });
    else if (o.name.startsWith("mcp__") && isObj(detail.input)) found.push({ phase: "after", tool: o.name, input: detail.input, cwd, id: o.callId, ok });
  };
  walk(page, 0);
  return found;
}

/** The sentence awt gave when it asked about a resend, from the hook JSON on its stdout; null when it did not ask. */
export function resendReason(stdout: string): string | null {
  try {
    const o = JSON.parse(stdout)?.hookSpecificOutput;
    return o?.permissionDecision === "ask" && typeof o.permissionDecisionReason === "string" ? o.permissionDecisionReason : null;
  } catch {
    return null;
  }
}
