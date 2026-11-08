import type { DebugSighting, Rect } from "../../lib/protocol.generated.ts";
import {
  LABEL_HEIGHT,
  labelWidth,
  outlineRect,
  placeLabel,
} from "./debugRegions.ts";
import type { Size } from "./layout.ts";

export type SightingKind = DebugSighting["kind"];

/** How long the fade at the end of a sighting's life takes. Short ones fade for their whole life. */
export const FADE_MS = 400;
/**
 * The observer can add four boxes a second while boosted. Past this many, the oldest go first, so
 * a burst can't pile up stale boxes over the game.
 */
export const MAX_SIGHTINGS = 24;

/** Short, so a label stays readable beside a small enemy. */
export const KIND_TAG: Record<SightingKind, string> = {
  noticed: "seen",
  look: "look",
  point: "point",
  look_back: "back",
};

export interface ShownSighting {
  id: number;
  sighting: DebugSighting;
  expiresAt: number;
}

export interface PlacedSighting {
  id: number;
  kind: SightingKind;
  outline: Rect;
  label: Rect;
  labelText: string;
  /** The id the rect reporter masks the label under, so the model never reads it back. */
  labelRectId: string;
  fadeDelayMs: number;
  fadeMs: number;
}

/** Drops what has expired, adds the new ones, and keeps only the newest MAX_SIGHTINGS. */
export function addSightings(
  current: ShownSighting[],
  incoming: DebugSighting[],
  now: number,
  firstId: number,
): ShownSighting[] {
  const added = incoming.map((sighting, index) => ({
    id: firstId + index,
    sighting,
    expiresAt: now + sighting.ttl_ms,
  }));
  return [...liveSightings(current, now), ...added].slice(-MAX_SIGHTINGS);
}

export function liveSightings(
  current: ShownSighting[],
  now: number,
): ShownSighting[] {
  return current.filter((shown) => shown.expiresAt > now);
}

/** When the next sighting runs out, for the one timer that prunes them. */
export function nextExpiry(current: ShownSighting[]): number | null {
  if (current.length === 0) return null;
  return Math.min(...current.map((shown) => shown.expiresAt));
}

/** The fade starts this long after a sighting appears and ends as its ttl runs out. */
export function fadeTiming(ttlMs: number): { delayMs: number; fadeMs: number } {
  const fadeMs = Math.min(FADE_MS, ttlMs);
  return { delayMs: ttlMs - fadeMs, fadeMs };
}

export function sightingLabel(sighting: DebugSighting): string {
  return `${KIND_TAG[sighting.kind]}: ${sighting.label}`;
}

/** look and look_back cover a whole area, often the game window, so labels needn't avoid them. */
function isArea(kind: SightingKind): boolean {
  return kind === "look" || kind === "look_back";
}

function clampInto(rect: Rect, viewport: Size): Rect {
  return {
    ...rect,
    x: Math.min(Math.max(rect.x, 0), Math.max(viewport.width - rect.width, 0)),
    y: Math.min(
      Math.max(rect.y, 0),
      Math.max(viewport.height - LABEL_HEIGHT, 0),
    ),
  };
}

function onScreen(rect: Rect, viewport: Size): boolean {
  return (
    rect.x >= 0 &&
    rect.y >= 0 &&
    rect.x + rect.width <= viewport.width &&
    rect.y + rect.height <= viewport.height
  );
}

/**
 * Labels go beside their box, clear of the small boxes, as the HUD view's do. A box that fills the
 * screen has no room outside it, so its label is pulled back onto the screen.
 */
export function placeSightings(
  shown: ShownSighting[],
  viewport: Size,
): PlacedSighting[] {
  const boxes = shown
    .filter(({ sighting }) => !isArea(sighting.kind))
    .map(({ sighting }) => sighting.rect);
  return shown.map(({ id, sighting }) => {
    const text = sightingLabel(sighting);
    const placed = placeLabel(
      sighting.rect,
      labelWidth(text),
      boxes,
      viewport,
    ).label;
    const label = onScreen(placed, viewport)
      ? placed
      : clampInto(placed, viewport);
    const { delayMs, fadeMs } = fadeTiming(sighting.ttl_ms);
    return {
      id,
      kind: sighting.kind,
      outline: outlineRect(sighting.rect),
      label,
      labelText: text,
      labelRectId: `debug-sighting-${id}`,
      fadeDelayMs: delayMs,
      fadeMs,
    };
  });
}
