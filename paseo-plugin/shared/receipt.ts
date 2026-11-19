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

function plural(n: number, [one, many]: [string, string]): string {
  return `${n} ${n === 1 ? one : many}`;
}

function andList(items: string[]): string {
  return items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/**
 * One plain muted line, for example `awt saved 1 decision and 1 note`, `awt saved an automatic handoff`,
 * `awt recalled 2 earlier records and saved 1 note`, or `awt saved nothing this turn`.
 * Ids are left out; shadow recall (never shown to the agent) is not mentioned.
 */
export function receiptLine(data: Receipt): string {
  const saved: string[] = [];
  if (!data.empty) {
    for (const type of RECEIPT_TYPES) {
      const n = data.counts[type] ?? 0;
      if (!n) continue;
      if (type === "state") {
        // The stand-in handoff is the plugin's, not the agent's: name it apart from handoffs the agent wrote.
        const own = data.auto ? n - 1 : n;
        if (own > 0) saved.push(plural(own, ["handoff", "handoffs"]));
        if (data.auto) saved.push("an automatic handoff");
        continue;
      }
      saved.push(plural(n, WORD[type]));
    }
  }
  const recalled = !data.shadow && data.recalled?.length ? `recalled ${plural(data.recalled.length, ["earlier record", "earlier records"])}` : "";
  if (recalled) return saved.length ? `awt ${recalled} and saved ${andList(saved)}` : `awt ${recalled}`;
  return saved.length ? `awt saved ${andList(saved)}` : "awt saved nothing this turn";
}
