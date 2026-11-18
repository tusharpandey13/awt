import { awt, parseJson } from "./awt.js";
import type { AwtConfig } from "./config.js";
import { RECEIPT_TYPES, type Receipt } from "../shared/receipt.js";

interface Row {
  type?: string;
  id?: string | null;
  by?: string | null;
  scope?: string | null;
  node?: string | null;
  ids?: string[] | null;
  result?: string | null;
}

/** The text of a recalled record, at most 80 chars, from `awt find --tree ID`; null when awt cannot say. Local only. */
async function recordText(cfg: AwtConfig, node: string, id: string, by: string): Promise<string | null> {
  const r = await awt({ ...cfg, timeoutMs: Math.min(cfg.timeoutMs, 1000) }, node, ["find", "--tree", id], by);
  if (r.code !== 0) return null;
  for (const line of r.stdout.split("\n")) {
    const m = line.startsWith(`event:${id}`) ? /^event:[^ :]+(?: @[^:]*)?: (.*)$/.exec(line) : null;
    if (m) return m[1].replace(id, "").trim().replace(/\s+/g, " ").slice(0, 80) || null;
  }
  return null;
}

/**
 * What awt stored in `node` and the nodes below it since `since`, read with `awt list --since --down --json`
 * (the plugin never reads .awt/ itself). Null when awt could not answer.
 */
export async function readReceipt(cfg: AwtConfig, node: string, since: Date, by: string): Promise<Receipt | null> {
  const r = await awt(cfg, node, ["list", "--since", since.toISOString(), "--down", "--json"], by);
  if (r.code !== 0) return null;
  const rows = parseJson<Row[] | null>(r.stdout, null);
  if (!Array.isArray(rows)) return null;
  const counts: Record<string, number> = {};
  const ids: string[] = [];
  const effects = new Set<string>();
  let autoStates = 0;
  const recalled: string[] = [];
  let hits = 0;
  for (const row of rows) {
    const type = row.type;
    // Passive recall rows of the agent's own node only; they are not stored work, so they never count.
    if (type === "recall" && !row.node && (row.result === "hits" || row.result === "shadow") && Array.isArray(row.ids) && row.ids.length) {
      for (const id of row.ids) if (recalled.length < 5 && !recalled.includes(id)) recalled.push(id);
      if (row.result === "hits") hits++;
      continue;
    }
    if (!type || !(RECEIPT_TYPES as readonly string[]).includes(type)) continue;
    // The plugin's own rows (parent notes, refs, status) are not the agent's work; only its stand-in handoff counts.
    if (row.by === "paseo-plugin" && !(type === "state" && row.scope === "auto")) continue;
    // An effect is several rows over its life; it counts once.
    if (type === "effect") {
      if (row.id && effects.has(row.id)) continue;
      if (row.id) effects.add(row.id);
    }
    counts[type] = (counts[type] ?? 0) + 1;
    if (type === "state") {
      if (row.scope === "auto") autoStates++;
    }
    if (row.id && ids.length < 5 && !ids.includes(row.id)) ids.push(row.id);
  }
  const receipt: Receipt = { node: node.split("/").filter(Boolean).pop() ?? node, counts, ids, auto: autoStates > 0, empty: Object.keys(counts).length === 0 };
  if (recalled.length) {
    const deadline = new Promise<null[]>((done) => setTimeout(() => done([]), 1000).unref());
    const texts = await Promise.race([Promise.all(recalled.map((id) => recordText(cfg, node, id, by))), deadline]);
    receipt.recalled = recalled.map((id, i) => (texts[i] ? { id, text: texts[i] as string } : { id }));
    if (!hits) receipt.shadow = true;
  }
  return receipt;
}
