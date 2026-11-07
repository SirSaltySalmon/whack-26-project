import type { ControlTab } from "../types.ts";
import { VoicesTab } from "./VoicesTab.tsx";

export const tab: ControlTab = {
  id: "voices",
  title: "Voices",
  order: 40,
  icon: "♪",
  Component: VoicesTab,
};
