import assert from "node:assert/strict";
import { test } from "node:test";
import { formatMs, moodTone, speed, tail } from "./debugBrain.ts";

test("a mood reads calm until it's clearly good or bad", () => {
  assert.equal(moodTone(0.6), "good");
  assert.equal(moodTone(0.1), "calm");
  assert.equal(moodTone(-0.1), "calm");
  assert.equal(moodTone(-0.5), "bad");
});

test("latency shows milliseconds, then seconds past one", () => {
  assert.equal(formatMs(182.4), "182 ms");
  assert.equal(formatMs(1125), "1.1 s");
});

test("latency is judged against the bark and first-audio budgets", () => {
  assert.equal(speed(180), "fast");
  assert.equal(speed(900), "ok");
  assert.equal(speed(2800), "slow");
});

test("a short transcript shows whole", () => {
  assert.equal(tail("  what's   the best boss? "), "what's the best boss?");
});

test("a long transcript keeps its newest words, from a word boundary", () => {
  const long = `${"word ".repeat(40)}and the newest part`;
  const shown = tail(long, 30);
  assert.ok(shown.startsWith("…"));
  assert.ok(shown.endsWith("and the newest part"));
  assert.ok(!shown.slice(1).startsWith(" "));
  assert.ok(shown.length <= 31);
});
