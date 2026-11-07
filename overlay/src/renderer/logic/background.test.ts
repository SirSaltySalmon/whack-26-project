import assert from "node:assert/strict";
import { test } from "node:test";
import {
  contentBounds,
  DEFAULT_BACKGROUND,
  removeBackground,
} from "./background.ts";

type Rgb = [number, number, number];
const WHITE: Rgb = [255, 255, 255];
const ORANGE: Rgb = [200, 120, 40];

/** Builds an opaque image from rows of single-letter colour codes. */
function image(rows: string[], colours: Record<string, Rgb>) {
  const height = rows.length;
  const width = rows[0]?.length ?? 0;
  const rgba = new Uint8ClampedArray(width * height * 4);
  rows.forEach((row, y) =>
    [...row].forEach((code, x) => {
      const colour = colours[code];
      if (!colour) throw new Error(`No colour for ${code}`);
      rgba.set([...colour, 255], (y * width + x) * 4);
    }),
  );
  const alpha = (x: number, y: number) => rgba[(y * width + x) * 4 + 3];
  return { rgba, width, height, alpha };
}

const colours = { w: WHITE, o: ORANGE, g: [235, 235, 235] as Rgb };

test("white reachable from the edges goes; white enclosed by the character stays", () => {
  const { rgba, width, height, alpha } = image(
    ["wwwwwww", "wooooow", "wowwwow", "wooooow", "wwwwwww"],
    colours,
  );
  const cleared = removeBackground(rgba, width, height, {
    ...DEFAULT_BACKGROUND,
    feather: 0,
  });
  assert.equal(alpha(0, 0), 0);
  assert.equal(alpha(6, 2), 0);
  // The white "chest" inside the orange outline isn't connected to the edge.
  assert.equal(alpha(2, 2), 255);
  assert.equal(alpha(3, 2), 255);
  assert.equal(alpha(1, 1), 255);
  // Just the border ring: 7 + 7 across, 3 + 3 down the sides.
  assert.equal(cleared, 20);
});

test("light grey watermark text on the background is removed with it", () => {
  const { rgba, width, height, alpha } = image(
    ["wwwww", "wgggw", "wwwww"],
    colours,
  );
  removeBackground(rgba, width, height);
  for (let x = 0; x < width; x += 1) assert.equal(alpha(x, 1), 0);
});

test("pale but coloured pixels at the edge aren't taken for white", () => {
  const cream: Rgb = [250, 225, 190];
  const { rgba, width, height, alpha } = image(["wcw"], { w: WHITE, c: cream });
  removeBackground(rgba, width, height, { ...DEFAULT_BACKGROUND, feather: 0 });
  assert.equal(alpha(1, 0), 255);
});

test("edge pixels are softened and unmixed from white, dark ones untouched", () => {
  const light: Rgb = [220, 200, 180];
  const { rgba, width, height, alpha } = image(["wlo"], {
    w: WHITE,
    l: light,
    o: ORANGE,
  });
  removeBackground(rgba, width, height, { ...DEFAULT_BACKGROUND, feather: 2 });
  const softened = alpha(1, 0) ?? 0;
  assert.ok(softened > 0 && softened < 255, `alpha ${softened}`);
  // Unmixing white makes the colour darker than it looked on white.
  assert.ok((rgba[4] ?? 255) < light[0]);
  // Orange's darkest channel is under the floor, so it keeps all its colour.
  assert.equal(alpha(2, 0), 255);
  assert.deepEqual([...rgba.slice(8, 11)], ORANGE);
});

test("an already transparent image floods the same way", () => {
  const rgba = new Uint8ClampedArray(3 * 4);
  rgba.set([10, 10, 10, 255], 4);
  assert.equal(removeBackground(rgba, 3, 1), 2);
  assert.equal(rgba[7], 255);
});

test("bad sizes do nothing", () => {
  assert.equal(removeBackground(new Uint8ClampedArray(4), 2, 2), 0);
  assert.equal(removeBackground(new Uint8ClampedArray(0), 0, 0), 0);
});

test("content bounds hug visible pixels, with padding clamped to the image", () => {
  const rgba = new Uint8ClampedArray(5 * 4 * 4);
  rgba[(1 * 5 + 2) * 4 + 3] = 255;
  rgba[(2 * 5 + 3) * 4 + 3] = 255;
  assert.deepEqual(contentBounds(rgba, 5, 4), {
    x: 2,
    y: 1,
    width: 2,
    height: 2,
  });
  assert.deepEqual(contentBounds(rgba, 5, 4, 5), {
    x: 0,
    y: 0,
    width: 5,
    height: 4,
  });
  assert.equal(contentBounds(new Uint8ClampedArray(16), 2, 2), null);
});

test("light grey rim pixels next to the background go, but not deeper inside", () => {
  const rim: Rgb = [205, 205, 200];
  const { rgba, width, height, alpha } = image(["wrooooorr"], {
    w: WHITE,
    r: rim,
    o: ORANGE,
  });
  removeBackground(rgba, width, height, { ...DEFAULT_BACKGROUND, feather: 2 });
  assert.equal(alpha(1, 0), 0);
  // The same grey further from the background is part of the character.
  assert.equal(alpha(7, 0), 255);
  assert.equal(alpha(8, 0), 255);
});
