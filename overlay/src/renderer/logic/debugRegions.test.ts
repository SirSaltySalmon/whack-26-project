import assert from "node:assert/strict";
import { test } from "node:test";
import type { DebugRegion, Rect } from "../../lib/protocol.generated.ts";
import {
  LABEL_GAP,
  LABEL_HEIGHT,
  OUTLINE_GAP,
  OUTLINE_WIDTH,
  outlineRect,
  placeRegions,
} from "./debugRegions.ts";

const screen = { width: 1920, height: 1080 };

function region(name: string, rect: Rect, display = "72/100"): DebugRegion {
  return { name, rect, status: "ok", display };
}

/** The gap between two rects, or a negative number if they overlap. */
function gap(a: Rect, b: Rect): number {
  const dx = Math.max(b.x - (a.x + a.width), a.x - (b.x + b.width));
  const dy = Math.max(b.y - (a.y + a.height), a.y - (b.y + b.height));
  return Math.max(dx, dy);
}

test("the outline's inner edge sits 4 DIP outside the box", () => {
  const rect = { x: 100, y: 200, width: 50, height: 20 };
  const outline = outlineRect(rect);
  assert.equal(OUTLINE_GAP, 4);
  assert.deepEqual(outline, {
    x: 100 - OUTLINE_GAP - OUTLINE_WIDTH,
    y: 200 - OUTLINE_GAP - OUTLINE_WIDTH,
    width: 50 + (OUTLINE_GAP + OUTLINE_WIDTH) * 2,
    height: 20 + (OUTLINE_GAP + OUTLINE_WIDTH) * 2,
  });
});

test("the label goes above the box with at least 24 DIP between them", () => {
  const rect = { x: 800, y: 500, width: 120, height: 30 };
  const [placed] = placeRegions([region("health", rect)], screen);
  assert.ok(placed);
  assert.equal(placed.side, "above");
  assert.equal(placed.label.y + LABEL_HEIGHT, rect.y - LABEL_GAP);
  assert.ok(gap(placed.label, rect) >= 24);
  assert.equal(placed.labelText, "health: 72/100");
});

test("a box at the top of the screen gets its label below", () => {
  const rect = { x: 1500, y: 10, width: 200, height: 24 };
  const [placed] = placeRegions([region("health", rect)], screen);
  assert.ok(placed);
  assert.equal(placed.side, "below");
  assert.equal(placed.label.y, rect.y + rect.height + LABEL_GAP);
});

test("a label near the right edge is pulled back on screen", () => {
  const rect = { x: 1900, y: 500, width: 20, height: 20 };
  const [placed] = placeRegions([region("mana", rect, "200/200")], screen);
  assert.ok(placed);
  assert.ok(placed.label.x + placed.label.width <= screen.width);
});

test("a label keeps clear of neighbouring boxes, not just its own", () => {
  const health = { x: 1500, y: 10, width: 200, height: 24 };
  // Right where health's label would go below it.
  const mana = { x: 1500, y: 70, width: 200, height: 20 };
  const placed = placeRegions(
    [region("health", health), region("mana", mana)],
    screen,
  );
  for (const item of placed) {
    assert.ok(gap(item.label, health) >= LABEL_GAP, `${item.name} vs health`);
    assert.ok(gap(item.label, mana) >= LABEL_GAP, `${item.name} vs mana`);
  }
});

test("only labels are reported for masking, never the outlines", () => {
  const regions = [
    region("health", { x: 800, y: 500, width: 120, height: 30 }),
    region("mana", { x: 400, y: 500, width: 120, height: 30 }),
  ];
  const placed = placeRegions(regions, screen);
  const ids = placed.map((item) => item.labelRectId);
  assert.equal(new Set(ids).size, regions.length);
  // What's reported must never touch a box, or that box's reader would read it as masked.
  for (const item of placed) {
    for (const { rect } of regions) assert.ok(gap(item.label, rect) >= 24);
  }
});

test("a missing reading still gets a label", () => {
  const [placed] = placeRegions(
    [
      {
        name: "defense",
        rect: { x: 800, y: 500, width: 40, height: 40 },
        status: "unreadable",
        display: null,
      },
    ],
    screen,
  );
  assert.equal(placed?.labelText, "defense: —");
  assert.equal(placed?.status, "unreadable");
});
