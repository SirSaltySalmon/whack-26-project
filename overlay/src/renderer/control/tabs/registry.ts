import { sortTabs } from "../logic/tabs.ts";
import type { ControlTab } from "./types.ts";

// Every `tabs/<name>/tab.tsx` is a tab. Adding one needs no change here or anywhere else.
const modules = import.meta.glob<{ tab: ControlTab }>("./*/tab.tsx", {
  eager: true,
});

export const TABS: ControlTab[] = sortTabs(
  Object.values(modules).map((module) => module.tab),
);
