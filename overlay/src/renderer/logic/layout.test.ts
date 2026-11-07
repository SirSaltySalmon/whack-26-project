import assert from "node:assert/strict";
import { test } from "node:test";
import {
  AVATAR_ASPECT,
  AVATAR_LIMITS,
  clampFrame,
  defaultAvatarFrame,
  minimizedTabPosition,
  moveFrame,
  resizeFrame,
  WEB_CARD_LIMITS,
} from "./layout.ts";

const screen = { width: 1920, height: 1080 };
const frame = { x: 100, y: 100, width: 300, height: 400 };

test("moving follows the drag", () => {
  assert.deepEqual(moveFrame(frame, 50, -20, screen), {
    ...frame,
    x: 150,
    y: 80,
  });
});

test("moving can't push a frame off any edge", () => {
  assert.deepEqual(moveFrame(frame, -5000, -5000, screen), {
    ...frame,
    x: 0,
    y: 0,
  });
  assert.deepEqual(moveFrame(frame, 5000, 5000, screen), {
    ...frame,
    x: 1620,
    y: 680,
  });
});

test("a frame larger than the screen shrinks to fit when clamped", () => {
  const huge = clampFrame({ x: 50, y: 50, width: 5000, height: 5000 }, screen);
  assert.deepEqual(huge, { x: 0, y: 0, width: 1920, height: 1080 });
});

test("free resizing changes each side independently and keeps the corner", () => {
  const resized = resizeFrame(frame, 100, -50, screen, WEB_CARD_LIMITS);
  assert.deepEqual(resized, { ...frame, width: 400, height: 350 });
});

test("free resizing respects the minimum and the screen edge", () => {
  assert.deepEqual(resizeFrame(frame, -5000, -5000, screen, WEB_CARD_LIMITS), {
    ...frame,
    width: 320,
    height: 240,
  });
  assert.deepEqual(resizeFrame(frame, 5000, 5000, screen, WEB_CARD_LIMITS), {
    ...frame,
    width: 1820,
    height: 980,
  });
});

test("the character keeps its 3:4 shape whichever way it's dragged", () => {
  for (const [dx, dy] of [
    [90, 0],
    [0, 120],
    [90, 500],
    [-200, -200],
    [5000, 5000],
  ] as const) {
    const resized = resizeFrame(frame, dx, dy, screen, AVATAR_LIMITS);
    assert.ok(Math.abs(resized.width / resized.height - AVATAR_ASPECT) < 1e-9);
    assert.ok(resized.y + resized.height <= screen.height + 1e-9);
    assert.ok(resized.x + resized.width <= screen.width + 1e-9);
    assert.ok(resized.width >= AVATAR_LIMITS.minWidth);
  }
});

test("the default character is 3:4 and on screen", () => {
  const avatar = defaultAvatarFrame(screen);
  assert.equal(avatar.width / avatar.height, AVATAR_ASPECT);
  assert.deepEqual(clampFrame(avatar, screen), avatar);
});

test("the minimized tab sits above the character, or below at the top of the screen", () => {
  assert.ok(minimizedTabPosition({ ...frame, y: 500 }, screen).y < 500);
  assert.ok(minimizedTabPosition({ ...frame, y: 0 }, screen).y > 400);
});
