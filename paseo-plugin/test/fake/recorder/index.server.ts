// H5 hook recorder (test code only). Appends {hook, ts, payload} as one JSON line to $AWT_HOOK_LOG.
// Requests are returned unchanged; nothing is redacted (fixture data is fictional).
import { appendFileSync } from "node:fs";

const EVENTS = ["agent.turn.before", "agent.turn.after", "agent.permission.before", "agent.permission.after", "agent.archive.after",
  "agent.create.after", "agent.close.after", "workspace.create.after", "workspace.archive.after", "worktree.create.after"];
const REQUESTS = ["worktree.create.before", "agent.create.before", "agent.open.before", "workspace.create.before"];

export default function contribute(server: any) {
  const log = (hook: string, payload: unknown) => {
    const f = process.env.AWT_HOOK_LOG;
    if (f) try { appendFileSync(f, JSON.stringify({ hook, ts: Date.now(), payload }) + "\n"); } catch {}
  };
  const offs: Array<() => void> = [];
  for (const h of EVENTS) offs.push(server.addHook(h, async (payload: unknown) => { log(h, payload); }));
  for (const h of REQUESTS) offs.push(server.addHook(h, async ({ request }: any) => { log(h, request); return request; }));
  return () => { for (const o of offs) try { o?.(); } catch {} };
}
