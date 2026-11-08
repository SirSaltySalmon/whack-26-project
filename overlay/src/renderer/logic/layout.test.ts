import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  AVATAR_ASPECT,
  AVATAR_LIMITS,
  CHAT_BOX_SIZE,
  CHAT_PILL_SIZE,
  chatPosition,
  clampFrame,
  defaultAvatarFrame,
  defaultSettingsFrame,
  minimizedTabPosition,
  moveFrame,
  resizeFrame,
  WEB_CARD_LIMITS,
  type Size,
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

const box = CHAT_BOX_SIZE;
const pill = CHAT_PILL_SIZE;

test("the chat box goes to the right of the character when there's room", () => {
  assert.deepEqual(chatPosition(frame, box, screen), { x: 408, y: 466 });
});

test("the chat box goes to the left when the right has no room", () => {
  assert.equal(chatPosition({ ...frame, x: 1620 }, box, screen).x, 1312);
});

test("a chat box that only just fits on the right stays there", () => {
  // 1312 + 300 (character) + 8 (gap) + 300 (box) is exactly the screen's width.
  assert.equal(chatPosition({ ...frame, x: 1312 }, box, screen).x, 1620);
  assert.equal(chatPosition({ ...frame, x: 1313 }, box, screen).x, 1005);
});

test("the pill takes the open box's side, so opening it doesn't jump across the character", () => {
  // The pill alone would fit on the right here; the open box wouldn't.
  const avatar = { ...frame, x: 1400 };
  assert.equal(chatPosition(avatar, pill, screen).x, 1400 - 8 - pill.width);
  assert.equal(chatPosition(avatar, box, screen).x, 1400 - 8 - box.width);
});

test("the chat box and pill sit level with the character's feet", () => {
  assert.equal(chatPosition(frame, box, screen).y, 500 - box.height);
  assert.equal(chatPosition(frame, pill, screen).y, 500 - pill.height);
});

test("a character hanging below the screen can't push the chat box off it", () => {
  // Frames can run off the bottom for a moment, if the screen shrinks before they're clamped.
  const { y } = chatPosition({ ...frame, y: 900 }, box, screen);
  assert.equal(y, screen.height - box.height);
});

test("the default character gets the chat box to its right, at its feet", () => {
  assert.deepEqual(chatPosition(defaultAvatarFrame(screen), box, screen), {
    x: 182,
    y: 1022,
  });
});

const overlaps = (
  a: { x: number; y: number } & Size,
  b: { x: number; y: number } & Size,
): boolean =>
  a.x < b.x + b.width &&
  b.x < a.x + a.width &&
  a.y < b.y + b.height &&
  b.y < a.y + a.height;

test("the chat stays on screen, and off the character and wiki tab when it can, wherever they are", () => {
  const gap = 8;
  for (const size of [
    { width: 75, height: 100 },
    { width: 150, height: 200 },
    { width: 600, height: 800 },
  ]) {
    for (let x = 0; x <= screen.width - size.width; x += 37) {
      for (let y = 0; y <= screen.height - size.height; y += 53) {
        const avatar = { ...size, x, y };
        const tab = {
          ...minimizedTabPosition(avatar, screen),
          width: 180,
          height: 32,
        };
        for (const chat of [box, pill]) {
          const placed = { ...chatPosition(avatar, chat, screen), ...chat };
          const label = JSON.stringify({ avatar, chat });

          assert.ok(placed.x >= 0 && placed.y >= 0, label);
          assert.ok(placed.x + chat.width <= screen.width, label);
          assert.ok(placed.y + chat.height <= screen.height, label);

          const roomOnRight = x + size.width + gap + box.width <= screen.width;
          const roomOnLeft = x >= chat.width + gap;
          if (roomOnRight || roomOnLeft) {
            assert.equal(overlaps(placed, avatar), false, label);
            assert.equal(overlaps(placed, tab), false, label);
          }
        }
      }
    }
  }
});

/** The width and height companion.css gives a class, from every rule that names it. */
function cssSize(className: string): Size {
  const css = readFileSync(
    new URL("../companion.css", import.meta.url),
    "utf-8",
  ).replace(/\/\*[\s\S]*?\*\//g, "");
  const declarations = css.split("}").flatMap((rule) => {
    const [selectors = "", body = ""] = rule.split("{");
    const names = selectors.split(",").map((selector) => selector.trim());
    return names.includes(`.${className}`)
      ? body.split(";").map((declaration) => declaration.trim())
      : [];
  });
  // startsWith skips min-width and max-width.
  const px = (property: string): number =>
    Number(
      declarations
        .find((declaration) => declaration.startsWith(`${property}:`))
        ?.match(/(\d+)px/)?.[1],
    );
  return { width: px("width"), height: px("height") };
}

test("the chat sizes used for placement match the CSS", () => {
  assert.deepEqual(cssSize("chat-box"), CHAT_BOX_SIZE);
  assert.deepEqual(cssSize("chat-pill"), CHAT_PILL_SIZE);
});

test("settings open tall enough for every row, but never past the screen", () => {
  assert.equal(defaultSettingsFrame(screen).height, 346);
  const short = { width: 800, height: 200 };
  const frame = defaultSettingsFrame(short);
  assert.ok(frame.y + frame.height <= short.height);
});
