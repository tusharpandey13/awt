import type { PluginClientContext } from "@getpaseo/plugin/client";
import { ReceiptRow } from "./client/receipt";
import { RECEIPT_KIND, RECEIPT_VERSION, receiptSchema } from "./shared/receipt";

export default function contribute(client: PluginClientContext) {
  return client.addTimelineRenderer({ kind: RECEIPT_KIND, version: RECEIPT_VERSION, schema: receiptSchema, Component: ReceiptRow });
}
