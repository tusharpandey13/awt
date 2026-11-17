import { Text, View } from "react-native";
import type { PluginTimelineItemProps } from "@getpaseo/plugin/client";
import { parseResend, type Resend } from "../shared/resend";

/** One line under the permission prompt. An item the schema rejects renders nothing. */
export function ResendRow({ theme, layout, item }: PluginTimelineItemProps<Resend>) {
  const data = parseResend(item);
  if (!data) return null;
  return (
    <View style={{ paddingVertical: 2, paddingHorizontal: layout.compact ? 12 : 16 }}>
      <Text style={{ color: theme.colors.foregroundMuted, fontSize: 12 }} numberOfLines={3}>
        {data.reason}
      </Text>
    </View>
  );
}
