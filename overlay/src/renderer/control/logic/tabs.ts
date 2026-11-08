import type { ControlTab } from "../tabs/types.ts";

/** Sidebar order, then title for ties. Two tabs with one id would share remembered state. */
export function sortTabs(tabs: readonly ControlTab[]): ControlTab[] {
  const seen = new Set<string>();
  for (const tab of tabs) {
    if (seen.has(tab.id))
      throw new Error(`Two Control Center tabs use id "${tab.id}"`);
    seen.add(tab.id);
  }
  return [...tabs].sort(
    (a, b) => a.order - b.order || a.title.localeCompare(b.title),
  );
}

/** The remembered tab if it still exists, otherwise the first. */
export function pickTab(
  tabs: readonly ControlTab[],
  remembered: string | null,
): ControlTab | undefined {
  return tabs.find((tab) => tab.id === remembered) ?? tabs[0];
}
