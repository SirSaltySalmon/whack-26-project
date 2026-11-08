import type { ControlTab } from "../types.ts";
import { MemoryTab } from "./MemoryTab.tsx";

export const tab: ControlTab = {
  id: "memory",
  title: "Memory",
  order: 30,
  icon: "◈",
  needsBrain: true,
  Component: MemoryTab,
};
