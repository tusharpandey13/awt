import type { PluginServerContext } from "@getpaseo/plugin/server";
import { registerHooks } from "./server/hooks";

export default function contribute(server: PluginServerContext) {
  return registerHooks(server);
}
