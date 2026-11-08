import assert from "node:assert/strict";
import { test } from "node:test";
import type { DebugSighting, Rect } from "../../lib/protocol.generated.ts";
import {
  addSightings,
  FADE_MS,
  fadeTiming,
  liveSightings,
  MAX_SIGHTINGS,
  nextExpiry,
  placeSightings,
  sightingLabel,
} from "./debugSightings.ts";
import type { Size } from "./layout.ts";

const screen = { width: 1920, height: 1080 };

function sighting(
  label: string,
  ttl_ms = 1600,
  kind: DebugSighting["kind"] = "noticed",
  rect: Rect = { x: 800, y: 500, width: 60, height: 40 },
): DebugSighting {
  return { label, rect, kind, ttl_ms };
}

function within(inner: Rect, outer: Size): boolean {
  return (
    inner.x >= 0 &&
    inner.y >= 0 &&
    inner.x + inner.width <= outer.width &&
    inner.y + inner.height <= outer.height
  );
}

test("each message adds to what is shown, and each sighting expires on its own ttl", () => {
  let shown = addSightings([], [sighting("slime", 1000)], 0, 0);
  shown = addSightings(shown, [sighting("door", 4000, "point")], 500, 1);
  assert.deepEqual(
    shown.map((s) => [s.id, s.expiresAt]),
    [
      [0, 1000],
      [1, 4500],
    ],
  );
  assert.deepEqual(
    liveSightings(shown, 999).map((s) => s.id),
    [0, 1],
  );
  assert.deepEqual(
    liveSightings(shown, 1000).map((s) => s.id),
    [1],
  );
  assert.deepEqual(liveSightings(shown, 4500), []);
});

test("adding drops what has already expired", () => {
  const first = addSightings([], [sighting("old", 1000)], 0, 0);
  const later = addSightings(first, [sighting("new")], 2000, 1);
  assert.deepEqual(
    later.map((s) => s.sighting.label),
    ["new"],
  );
});

test("a burst keeps only the newest sightings", () => {
  const burst = Array.from({ length: MAX_SIGHTINGS + 5 }, (_, i) =>
    sighting(`thing ${i}`),
  );
  const shown = addSightings([], burst, 0, 0);
  assert.equal(shown.length, MAX_SIGHTINGS);
  assert.equal(shown[0]?.sighting.label, "thing 5");
  assert.equal(new Set(shown.map((s) => s.id)).size, MAX_SIGHTINGS);
});

test("the prune timer waits for whichever sighting runs out first", () => {
  assert.equal(nextExpiry([]), null);
  const shown = addSightings(
    [],
    [sighting("a", 4000), sighting("b", 1600)],
    100,
    0,
  );
  assert.equal(nextExpiry(shown), 1700);
});

test("the fade ends exactly when the ttl runs out", () => {
  assert.deepEqual(fadeTiming(4000), {
    delayMs: 4000 - FADE_MS,
    fadeMs: FADE_MS,
  });
  // Shorter than a fade: fades for its whole life rather than starting late.
  assert.deepEqual(fadeTiming(200), { delayMs: 0, fadeMs: 200 });
});

test("labels say which kind of look found the box", () => {
  assert.equal(sightingLabel(sighting("green slime")), "seen: green slime");
  assert.equal(sightingLabel(sighting("door", 1, "point")), "point: door");
  assert.equal(sightingLabel(sighting("hit?", 1, "look_back")), "back: hit?");
});

test("each placed sighting has its own rect id and keeps its label clear of its box", () => {
  const rect = { x: 800, y: 500, width: 60, height: 40 };
  const shown = addSightings(
    [],
    [
      sighting("a", 1600, "noticed", rect),
      sighting("b", 1600, "noticed", rect),
    ],
    0,
    7,
  );
  const placed = placeSightings(shown, screen);
  assert.deepEqual(
    placed.map((p) => p.labelRectId),
    ["debug-sighting-7", "debug-sighting-8"],
  );
  const label = placed[0]!.label;
  assert.ok(
    label.y + label.height <= rect.y || label.y >= rect.y + rect.height,
  );
});

test("a look at the whole screen still gets its label on screen", () => {
  const whole = { x: 0, y: 0, width: screen.width, height: screen.height };
  const shown = addSightings(
    [],
    [sighting("what's that?", 4000, "look", whole)],
    0,
    0,
  );
  const [placed] = placeSightings(shown, screen);
  assert.ok(placed && within(placed.label, screen));
});
