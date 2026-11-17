import type { PluginClientContext } from "@getpaseo/plugin/client";
import { ReceiptRow } from "./client/receipt";
import { ResendRow } from "./client/resend";
import { RECEIPT_KIND, RECEIPT_VERSION, receiptSchema } from "./shared/receipt";
import { RESEND_KIND, RESEND_VERSION, resendSchema } from "./shared/resend";

export default function contribute(client: PluginClientContext) {
  const off = [
    client.addTimelineRenderer({ kind: RECEIPT_KIND, version: RECEIPT_VERSION, schema: receiptSchema, Component: ReceiptRow }),
    client.addTimelineRenderer({ kind: RESEND_KIND, version: RESEND_VERSION, schema: resendSchema, Component: ResendRow }),
  ];
  return () => off.forEach((f) => f());
}
