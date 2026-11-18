import { z } from "zod";

/** The plugin timeline row that shows what awt stored during one turn. */
export const RECEIPT_KIND = "awt-receipt";
export const RECEIPT_VERSION = 1;

export const RECEIPT_TYPES = ["decision", "question", "answer", "note", "ref", "state", "effect", "capture"] as const;

export const receiptSchema = z.object({
  /** Name of the agent's node directory. */
  node: z.string(),
  /** Rows stored this turn, per type. Types with no rows are absent. */
  counts: z.record(z.string(), z.number().int().nonnegative()),
  /** At most 5 ids of the rows stored. */
  ids: z.array(z.string()).max(5),
  /** True when the only state written was the plugin's stand-in handoff. */
  auto: z.boolean(),
  /** True when nothing was stored. */
  empty: z.boolean(),
  /** At most 5 records passive recall showed (or, with `shadow`, would have shown) this turn. `text` is local only and may be missing. Absent on a receipt without recall. */
  recalled: z.array(z.object({ id: z.string(), text: z.string().max(80).optional() })).max(5).optional(),
  /** True when the recalled records were not shown to the agent (AWT_RECALL=shadow). */
  shadow: z.boolean().optional(),
});
export type Receipt = z.infer<typeof receiptSchema>;

/** The receipt in an item, or null when the item is not a version 1 receipt. Never throws. */
export function parseReceipt(item: unknown): Receipt | null {
  try {
    const it = item as { version?: unknown; data?: unknown } | null | undefined;
    if (!it || it.version !== RECEIPT_VERSION) return null;
    const r = receiptSchema.safeParse(it.data);
    return r.success ? r.data : null;
  } catch {
    return null;
  }
}

const WORD: Record<string, [string, string]> = {
  decision: ["decision", "decisions"],
  question: ["question", "questions"],
  answer: ["answer", "answers"],
  note: ["note", "notes"],
  ref: ["ref", "refs"],
  effect: ["effect", "effects"],
  capture: ["capture", "captures"],
};

/** One muted line, for example `awt · 1 decision d-9e01b2c3 · 1 note · handoff`. */
export function receiptLine(data: Receipt): string {
  const parts: string[] = [];
  if (data.recalled?.length) {
    const list = data.recalled.map((r) => (r.text ? `${r.id} "${r.text}"` : r.id)).join(", ");
    parts.push(data.shadow ? `would recall ${list} (shadow)` : `recalled ${list}`);
  }
  if (data.empty) return ["awt", ...parts, "nothing stored this turn"].join(" · ");
  for (const type of RECEIPT_TYPES) {
    const n = data.counts[type] ?? 0;
    if (!n) continue;
    if (type === "state") {
      // The stand-in handoff is the plugin's, not the agent's: show it apart from handoffs the agent wrote.
      const own = data.auto ? n - 1 : n;
      if (own > 0) parts.push(data.auto ? `${own} handoff${own > 1 ? "s" : ""}` : n > 1 ? `${n} handoffs` : "handoff");
      if (data.auto) parts.push("handoff [auto]");
      continue;
    }
    const id = n === 1 && (type === "decision" || type === "question") ? data.ids.find((i) => i.startsWith(type[0] + "-")) : undefined;
    parts.push(`${n} ${WORD[type][n === 1 ? 0 : 1]}${id ? " " + id : ""}`);
  }
  return ["awt", ...parts].join(" · ");
}
