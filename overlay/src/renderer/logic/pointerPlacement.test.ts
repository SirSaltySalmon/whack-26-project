import assert from "node:assert/strict";
import { test } from "node:test";
import { placePointer, POINTER_BODY } from "./pointerPlacement.ts";

const screen = { width: 1920, height: 1080 };

test("without a box, the tip lands on the point", () => {
  assert.deepEqual(placePointer({ x: 500, y: 400 }, null, screen), {
    x: 500,
    y: 400,
    flipX: false,
    flipY: false,
  });
});

test("with a box, the pointer sits below it without covering it", () => {
  const target = { x: 400, y: 300, width: 200, height: 100 };
  const placed = placePointer({ x: 500, y: 350 }, target, screen);
  assert.deepEqual(placed, { x: 500, y: 400, flipX: false, flipY: false });
});

test("a box at the bottom of the screen puts the pointer above it", () => {
  const target = { x: 400, y: 1000, width: 200, height: 60 };
  const placed = placePointer({ x: 500, y: 1030 }, target, screen);
  assert.deepEqual(placed, { x: 500, y: 1000, flipX: false, flipY: true });
});

test("near the right edge the body flips so the label stays on screen", () => {
  const placed = placePointer({ x: 1900, y: 400 }, null, screen);
  assert.equal(placed.flipX, true);
  assert.ok(placed.x - POINTER_BODY.width >= 0);
});

test("points off screen are pulled back on", () => {
  const placed = placePointer({ x: -50, y: 5000 }, null, screen);
  assert.equal(placed.x, 0);
  assert.equal(placed.y, 1080);
});
