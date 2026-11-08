import assert from "node:assert/strict";
import { test } from "node:test";
import { menuPosition } from "./menuPosition.ts";

test("menus float below a trigger and flip above near the bottom", () => {
  const size = { width: 150, height: 100 };
  const viewport = { width: 800, height: 600 };
  assert.deepEqual(
    menuPosition({ top: 80, bottom: 110, right: 700 }, size, viewport),
    { top: 116, left: 550 },
  );
  assert.deepEqual(
    menuPosition({ top: 560, bottom: 590, right: 700 }, size, viewport),
    { top: 454, left: 550 },
  );
});

test("menu placement stays inside the viewport at either horizontal edge", () => {
  const menu = { width: 150, height: 100 };
  const viewport = { width: 300, height: 200 };
  assert.equal(
    menuPosition({ top: 80, bottom: 110, right: 20 }, menu, viewport).left,
    8,
  );
  assert.equal(
    menuPosition({ top: 80, bottom: 110, right: 500 }, menu, viewport).left,
    142,
  );
});
