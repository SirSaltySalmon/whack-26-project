import type { ControlTab } from "../types.ts";
import { LatencyTab } from "./LatencyTab.tsx";

export const tab: ControlTab = {
  id: "latency",
  title: "Latency",
  // Next to the Console, since both read the brain's log.
  order: 80,
  icon: "◷",
  Component: LatencyTab,
};
