/** Keep a floating menu beside its trigger and inside the current viewport. */
export function menuPosition(
  trigger: { top: number; bottom: number; right: number },
  menu: { width: number; height: number },
  viewport: { width: number; height: number },
): { top: number; left: number } {
  const pad = 8;
  const below = trigger.bottom + 6;
  return {
    left: Math.max(
      pad,
      Math.min(trigger.right - menu.width, viewport.width - menu.width - pad),
    ),
    top: Math.max(
      pad,
      Math.min(
        below + menu.height <= viewport.height - pad
          ? below
          : trigger.top - menu.height - 6,
        viewport.height - menu.height - pad,
      ),
    ),
  };
}
