import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULT_SKIN, parseSkin, SKINS } from "./skins.ts";

test("every listed skin parses to itself", () => {
  for (const skin of SKINS) assert.equal(parseSkin(skin.id), skin.id);
});

test("unknown or missing values fall back to the default", () => {
  for (const value of [null, undefined, "", "neon", 3, { id: "pixel" }]) {
    assert.equal(parseSkin(value), DEFAULT_SKIN);
  }
});

test("skin ids are unique", () => {
  const ids = SKINS.map((skin) => skin.id);
  assert.equal(new Set(ids).size, ids.length);
});
