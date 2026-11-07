import assert from "node:assert/strict";
import { test } from "node:test";
import { isWebUrl } from "../../lib/web.ts";
import { sameRects, visibleRects } from "./rects.ts";

const item = (element_id: string, x = 0, width = 10) => ({
  element_id,
  rect: { x, y: 0, width, height: 10 },
});

test("identical rects need no report", () => {
  assert.equal(sameRects([item("a")], [item("a")]), true);
  assert.equal(sameRects([], []), true);
});

test("moving, resizing, opening and closing all count as changes", () => {
  assert.equal(sameRects([item("a", 0)], [item("a", 1)]), false);
  assert.equal(sameRects([item("a", 0, 10)], [item("a", 0, 11)]), false);
  assert.equal(sameRects([item("a")], [item("a"), item("b")]), false);
  assert.equal(sameRects([item("a"), item("b")], [item("a")]), false);
  assert.equal(sameRects([item("a")], [item("b")]), false);
});

test("empty rects aren't reported", () => {
  assert.deepEqual(visibleRects([item("a"), item("b", 0, 0)]), [item("a")]);
});

test("only http and https pages can load", () => {
  assert.equal(isWebUrl("https://terraria.wiki.gg/wiki/Eye_of_Cthulhu"), true);
  assert.equal(isWebUrl("http://example.com"), true);
  for (const url of [
    "file:///C:/x",
    "javascript:alert(1)",
    "data:text/html,x",
    "steam://run/1",
    "nope",
    "",
  ]) {
    assert.equal(isWebUrl(url), false, url);
  }
});
