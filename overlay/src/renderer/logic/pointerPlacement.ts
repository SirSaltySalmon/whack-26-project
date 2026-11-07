import type { Size } from "./layout.ts";

export interface TargetBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface PointerPlacement {
  /** Where the arrow's tip goes. The body extends away from it, down and right unless flipped. */
  x: number;
  y: number;
  flipX: boolean;
  flipY: boolean;
}

/** The most room the arrow and its label can take, used to decide when to flip. */
export const POINTER_BODY: Size = { width: 260, height: 72 };

/**
 * Sits on the target's edge, not over it: the pointer's rectangle is masked, so covering the target
 * would hide it from the next vision call.
 */
export function placePointer(
  point: { x: number; y: number },
  target: TargetBox | null | undefined,
  viewport: Size,
): PointerPlacement {
  const bottom = target ? target.y + target.height : point.y;
  const top = target ? target.y : point.y;
  const tipX = target ? target.x + target.width / 2 : point.x;

  const flipY = bottom + POINTER_BODY.height > viewport.height;
  const flipX = tipX + POINTER_BODY.width > viewport.width;
  return {
    x: Math.min(Math.max(tipX, 0), viewport.width),
    y: Math.min(Math.max(flipY ? top : bottom, 0), viewport.height),
    flipX,
    flipY,
  };
}
