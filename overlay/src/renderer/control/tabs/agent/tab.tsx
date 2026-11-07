import type { ControlTab } from "../types.ts";
import { AgentTab } from "./AgentTab.tsx";

export const tab: ControlTab = {
  id: "agent",
  title: "Agent",
  order: 10,
  icon: "✦",
  Component: AgentTab,
};
