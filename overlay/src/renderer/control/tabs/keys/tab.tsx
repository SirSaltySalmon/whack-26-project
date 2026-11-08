import type { ControlTab } from "../types.ts";
import { KeysTab } from "./KeysTab.tsx";

export const tab: ControlTab = {
  id: "keys",
  title: "Keys",
  order: 20,
  icon: "⚿",
  Component: KeysTab,
};
