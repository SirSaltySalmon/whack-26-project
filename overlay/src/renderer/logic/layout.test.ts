import assert from "node:assert/strict";
import { test } from "node:test";
import {
  AVATAR_ASPECT,
  AVATAR_LIMITS,
  clampFrame,
  defaultAvatarFrame,
  defaultSettingsFrame,
  minimizedTabPosition,
  moveFrame,
  questionPlacement,
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

test("a question goes to the right of the character when there's room", () => {
  assert.equal(questionPlacement(frame, screen).left, 412);
});

test("a question goes to the left when the right has no room", () => {
  assert.equal(questionPlacement({ ...frame, x: 1620 }, screen).left, 1308);
});

test("a question that only just fits on the right stays there", () => {
  // 1308 + 300 (character) + 12 (gap) + 300 (question) is exactly the screen's width.
  assert.equal(questionPlacement({ ...frame, x: 1308 }, screen).left, 1620);
  assert.equal(questionPlacement({ ...frame, x: 1309 }, screen).left, 997);
});

test("a question beside a character on the left edge goes to its right", () => {
  assert.equal(questionPlacement({ ...frame, x: 0 }, screen).left, 312);
});

test("with no room on either side a question stops at the screen's left edge", () => {
  const narrow = { width: 700, height: 1080 };
  assert.equal(questionPlacement({ ...frame, x: 313 }, narrow).left, 1);
  assert.equal(questionPlacement({ ...frame, x: 312 }, narrow).left, 0);
  assert.equal(questionPlacement({ ...frame, x: 100 }, narrow).left, 0);
});

test("a question lines up with the bottom of the character", () => {
  assert.equal(questionPlacement(frame, screen).bottom, 580);
  assert.equal(questionPlacement({ ...frame, y: 680 }, screen).bottom, 0);
});

test("a character hanging below the screen can't push a question off it", () => {
  // Frames can run off the bottom for a moment, if the screen shrinks before they're clamped.
  assert.equal(questionPlacement({ ...frame, y: 900 }, screen).bottom, 0);
});

test("a small character at the top still leaves a question room to grow upward", () => {
  // A question is anchored by its bottom edge, so lining up with this one would lose its top.
  const small = { x: 0, y: 0, width: 75, height: 100 };
  assert.equal(questionPlacement(small, screen).bottom, 920);
  // The character's edge is used again as soon as it's low enough.
  assert.equal(questionPlacement({ ...small, y: 60 }, screen).bottom, 920);
  assert.equal(questionPlacement({ ...small, y: 61 }, screen).bottom, 919);
});

test("a screen too short for a question keeps it on the bottom edge", () => {
  const short = { width: 1920, height: 100 };
  const small = { x: 0, y: 0, width: 75, height: 100 };
  assert.equal(questionPlacement(small, short).bottom, 0);
});

test("the default character gets a question to its right, level with it", () => {
  assert.deepEqual(questionPlacement(defaultAvatarFrame(screen), screen), {
    left: 186,
    bottom: 24,
  });
});

test("a question stays on screen, and off the character when it can, wherever that is", () => {
  const questionWidth = 300;
  const gap = 12;
  for (const size of [
    { width: 75, height: 100 },
    { width: 150, height: 200 },
    { width: 600, height: 800 },
  ]) {
    for (let x = 0; x <= screen.width - size.width; x += 37) {
      for (let y = 0; y <= screen.height - size.height; y += 53) {
        const avatar = { ...size, x, y };
        const { left, bottom } = questionPlacement(avatar, screen);
        const label = JSON.stringify(avatar);

        assert.ok(left >= 0, label);
        assert.ok(left + questionWidth <= screen.width, label);
        assert.ok(bottom >= 0, label);
        assert.ok(screen.height - bottom >= 160, label);

        const roomOnLeft = x >= questionWidth + gap;
        const roomOnRight =
          x + size.width + gap + questionWidth <= screen.width;
        if (roomOnLeft || roomOnRight) {
          const overlaps = left < x + size.width && x < left + questionWidth;
          assert.equal(overlaps, false, label);
        }
      }
    }
  }
});

test("settings open tall enough for every row, but never past the screen", () => {
  assert.equal(defaultSettingsFrame(screen).height, 290);
  const short = { width: 800, height: 200 };
  const frame = defaultSettingsFrame(short);
  assert.ok(frame.y + frame.height <= short.height);
});
