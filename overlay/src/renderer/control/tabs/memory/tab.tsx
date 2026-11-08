import type { ControlTab } from "../types.ts";
import { MemoryTab } from "./MemoryTab.tsx";

export const tab: ControlTab = {
  id: "memory",
  title: "Memory",
  order: 30,
  icon: "◈",
  // Memory is read from disk with the partner off, so the tab always works.
  Component: MemoryTab,
};
