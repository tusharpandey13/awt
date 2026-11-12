import { Text, View } from "react-native";
import type { PluginTimelineItemProps } from "@getpaseo/plugin/client";
import { parseReceipt, receiptLine, type Receipt } from "../shared/receipt";

/** One muted line. An item the schema rejects renders nothing. */
export function ReceiptRow({ theme, layout, item }: PluginTimelineItemProps<Receipt>) {
  const data = parseReceipt(item);
  if (!data) return null;
  return (
    <View style={{ paddingVertical: 2, paddingHorizontal: layout.compact ? 12 : 16 }}>
      <Text style={{ color: theme.colors.foregroundMuted, fontSize: 12 }} numberOfLines={2}>
        {receiptLine(data)}
      </Text>
    </View>
  );
}
