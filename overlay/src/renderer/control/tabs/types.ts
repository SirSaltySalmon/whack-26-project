import type { ComponentType } from "react";

/**
 * One Control Center tab. To add a tab, create `tabs/<name>/tab.tsx` exporting `tab`; the
 * registry finds it, so no shared file changes. Reach the brain and launcher only through
 * `useControl()` from `../ControlContext.tsx`.
 */
export interface ControlTab {
  /** Stable, because the window reopens on the last tab used. */
  id: string;
  title: string;
  /** Sidebar position. Used in tens (10 Agent ... 90 Console) so new tabs fit between. */
  order: number;
  /** One or two characters. No icon library. */
  icon: string;
  /** Shows "start the partner" instead of the tab while no brain is connected. */
  needsBrain?: boolean;
  Component: ComponentType;
}
