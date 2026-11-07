import assert from "node:assert/strict";
import { test } from "node:test";
import { MouseCapture } from "./mouseCapture.ts";

function make(): { capture: MouseCapture; calls: boolean[] } {
  const calls: boolean[] = [];
  return { capture: new MouseCapture((value) => calls.push(value)), calls };
}

test("captures only while over an interactive element", () => {
  const { capture, calls } = make();
  capture.hover(true);
  capture.hover(false);
  assert.deepEqual(calls, [true, false]);
});

test("repeated hovers don't spam the main process", () => {
  const { capture, calls } = make();
  capture.hover(false);
  capture.hover(true);
  capture.hover(true);
  capture.hover(true);
  assert.deepEqual(calls, [true]);
});

test("capture holds through a drag even when the cursor leaves the handle", () => {
  const { capture, calls } = make();
  capture.hover(true);
  capture.beginGesture();
  capture.hover(false);
  assert.deepEqual(calls, [true]);
  assert.equal(capture.isGesturing, true);
});

test("a drag ending away from any element releases the mouse", () => {
  const { capture, calls } = make();
  capture.hover(true);
  capture.beginGesture();
  capture.endGesture(false);
  assert.deepEqual(calls, [true, false]);
  assert.equal(capture.isGesturing, false);
});

test("a drag ending over an element keeps capturing", () => {
  const { capture, calls } = make();
  capture.hover(true);
  capture.beginGesture();
  capture.endGesture(true);
  assert.deepEqual(calls, [true]);
});
