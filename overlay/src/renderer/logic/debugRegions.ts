import type { DebugRegion, Rect } from "../../lib/protocol.generated.ts";
import type { Size } from "./layout.ts";

/** The outline sits outside the box so it never covers what the reader is reading. */
export const OUTLINE_GAP = 4;
export const OUTLINE_WIDTH = 2;
/**
 * Labels are reported for masking, so they keep well clear of every box: the brain pads masks by
 * a few pixels, and a label inside that padding would make its own region read as masked.
 */
export const LABEL_GAP = 24;
// Fixed sizes, set in debugRegions.css too, so placement here matches what's drawn exactly.
export const LABEL_HEIGHT = 20;
export const LABEL_CHAR_WIDTH = 7.5; // 12px monospace, with room to spare
export const LABEL_PADDING_X = 8;
export const LABEL_MAX_WIDTH = 240;

export type Side = "above" | "below" | "right" | "left";

export interface PlacedRegion {
  name: string;
  status: DebugRegion["status"];
  /** Drawn but never reported: masking it would cover the HUD box and hide it from the reader. */
  outline: Rect;
  label: Rect;
  labelText: string;
  side: Side;
  /** The id the rect reporter masks the label under. */
  labelRectId: string;
}

export function labelText(region: DebugRegion): string {
  return `${region.name}: ${region.display ?? "—"}`;
}

export function labelWidth(text: string): number {
  return Math.min(
    Math.ceil(text.length * LABEL_CHAR_WIDTH) + LABEL_PADDING_X * 2,
    LABEL_MAX_WIDTH,
  );
}

export function outlineRect(rect: Rect): Rect {
  const grow = OUTLINE_GAP + OUTLINE_WIDTH;
  return {
    x: rect.x - grow,
    y: rect.y - grow,
    width: rect.width + grow * 2,
    height: rect.height + grow * 2,
  };
}

function grown(rect: Rect, by: number): Rect {
  return {
    x: rect.x - by,
    y: rect.y - by,
    width: rect.width + by * 2,
    height: rect.height + by * 2,
  };
}

function overlaps(a: Rect, b: Rect): boolean {
  return (
    a.x < b.x + b.width &&
    b.x < a.x + a.width &&
    a.y < b.y + b.height &&
    b.y < a.y + a.height
  );
}

function onScreen(rect: Rect, viewport: Size): boolean {
  return (
    rect.x >= 0 &&
    rect.y >= 0 &&
    rect.x + rect.width <= viewport.width &&
    rect.y + rect.height <= viewport.height
  );
}

function clampX(x: number, width: number, viewport: Size): number {
  return Math.min(Math.max(x, 0), Math.max(viewport.width - width, 0));
}

function clampY(y: number, viewport: Size): number {
  return Math.min(Math.max(y, 0), Math.max(viewport.height - LABEL_HEIGHT, 0));
}

function candidate(rect: Rect, width: number, side: Side, viewport: Size) {
  const height = LABEL_HEIGHT;
  switch (side) {
    case "above":
      return {
        x: clampX(rect.x, width, viewport),
        y: rect.y - LABEL_GAP - height,
        width,
        height,
      };
    case "below":
      return {
        x: clampX(rect.x, width, viewport),
        y: rect.y + rect.height + LABEL_GAP,
        width,
        height,
      };
    case "right":
      return {
        x: rect.x + rect.width + LABEL_GAP,
        y: clampY(rect.y, viewport),
        width,
        height,
      };
    case "left":
      return {
        x: rect.x - LABEL_GAP - width,
        y: clampY(rect.y, viewport),
        width,
        height,
      };
  }
}

const SIDES: Side[] = ["above", "below", "right", "left"];

/**
 * Above the box by preference, else whichever side is on screen and keeps LABEL_GAP from every
 * box. HUD regions sit close together, so a label beside one box must not land on another.
 */
export function placeLabel(
  rect: Rect,
  width: number,
  boxes: Rect[],
  viewport: Size,
): { label: Rect; side: Side } {
  const clearOf = boxes.map((box) => grown(box, LABEL_GAP));
  const fits = (label: Rect) =>
    onScreen(label, viewport) && !clearOf.some((box) => overlaps(label, box));
  for (const side of SIDES) {
    const label = candidate(rect, width, side, viewport);
    if (fits(label)) return { label, side };
  }
  // Crowded or tiny screen: stay clear of this box at least, so its own reader isn't masked.
  const own = grown(rect, LABEL_GAP);
  for (const side of SIDES) {
    const label = candidate(rect, width, side, viewport);
    if (onScreen(label, viewport) && !overlaps(label, own)) {
      return { label, side };
    }
  }
  return { label: candidate(rect, width, "below", viewport), side: "below" };
}

export function placeRegions(
  regions: DebugRegion[],
  viewport: Size,
): PlacedRegion[] {
  const boxes = regions.map((region) => region.rect);
  return regions.map((region, index) => {
    const text = labelText(region);
    const { label, side } = placeLabel(
      region.rect,
      labelWidth(text),
      boxes,
      viewport,
    );
    return {
      name: region.name,
      status: region.status,
      outline: outlineRect(region.rect),
      label,
      labelText: text,
      side,
      // Indexed, because the brain's names aren't promised to be unique.
      labelRectId: `debug-label-${index}`,
    };
  });
}
