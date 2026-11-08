import type { ControlTab } from "../types.ts";
import { ConsoleTab } from "./ConsoleTab.tsx";

export const tab: ControlTab = {
  id: "console",
  title: "Console",
  order: 90,
  icon: "›_",
  Component: ConsoleTab,
};
