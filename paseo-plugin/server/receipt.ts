import { awt, parseJson } from "./awt.js";
import type { AwtConfig } from "./config.js";
import { RECEIPT_TYPES, type Receipt } from "../shared/receipt.js";

interface Row {
  type?: string;
  id?: string | null;
  by?: string | null;
  scope?: string | null;
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
  for (const row of rows) {
    const type = row.type;
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
  return { node: node.split("/").filter(Boolean).pop() ?? node, counts, ids, auto: autoStates > 0, empty: Object.keys(counts).length === 0 };
}
