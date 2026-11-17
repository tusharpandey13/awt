import { z } from "zod";

/** The plugin timeline row that tells the person a tool call repeats a send awt already has as sent or unknown. */
export const RESEND_KIND = "awt-resend";
export const RESEND_VERSION = 1;

export const resendSchema = z.object({
  /** awt's own sentence, naming the earlier effect id and its ref. */
  reason: z.string().max(600),
});
export type Resend = z.infer<typeof resendSchema>;

/** The data of a version 1 resend note, or null. Never throws. */
export function parseResend(item: unknown): Resend | null {
  try {
    const it = item as { version?: unknown; data?: unknown } | null | undefined;
    if (!it || it.version !== RESEND_VERSION) return null;
    const r = resendSchema.safeParse(it.data);
    return r.success ? r.data : null;
  } catch {
    return null;
  }
}
