import type { ControlTab } from "../types.ts";
import { PacingTab } from "./PacingTab.tsx";

export const tab: ControlTab = {
  id: "pacing",
  title: "Pacing",
  order: 15,
  icon: "⏱",
  Component: PacingTab,
};
