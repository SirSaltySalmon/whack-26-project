import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import type { SubtitleChunk } from "../../lib/protocol.generated.ts";
import {
  applySubtitle,
  endStaleSubtitle,
  type SubtitleLine,
} from "./subtitles.ts";

const chunk = (
  utterance_id: string,
  text: string,
  final = false,
): SubtitleChunk => ({ type: "subtitle.chunk", utterance_id, text, final });

const words = (utterance_id: string, ...texts: string[]): SubtitleChunk[] =>
  texts.map((text) => chunk(utterance_id, text));

const play = (
  chunks: SubtitleChunk[],
  start: SubtitleLine | null = null,
): SubtitleLine | null =>
  chunks.reduce<SubtitleLine | null>(
    (line, next) => applySubtitle(line, next),
    start,
  );

test("the first word starts a line that isn't done yet", () => {
  assert.deepEqual(applySubtitle(null, chunk("a", "That")), {
    utteranceId: "a",
    text: "That",
    done: false,
  });
});

test("word chunks join with spaces", () => {
  assert.deepEqual(play(words("a", "That", "looks", "rough")), {
    utteranceId: "a",
    text: "That looks rough",
    done: false,
  });
});

test("no space goes before punctuation", () => {
  const sentence = words(
    "a",
    "Nice",
    "dodge",
    ",",
    "that",
    "was",
    "close",
    "!",
  );
  assert.equal(play(sentence)?.text, "Nice dodge, that was close!");

  for (const mark of [".", ",", "!", "?", ";", ":", "'s", "’s", ")"]) {
    assert.equal(play(words("a", "word", mark))?.text, `word${mark}`, mark);
  }
});

test("a chunk that brings its own space doesn't get a second one", () => {
  assert.equal(play(words("a", "Nice ", "dodge"))?.text, "Nice dodge");
  assert.equal(play(words("a", "Nice", " dodge"))?.text, "Nice dodge");
});

test("a single final chunk shows the whole line at once", () => {
  assert.deepEqual(applySubtitle(null, chunk("a", "That looks rough.", true)), {
    utteranceId: "a",
    text: "That looks rough.",
    done: true,
  });
});

test("an empty final chunk marks the line done and leaves its text alone", () => {
  const spoken = play(words("a", "That", "looks", "rough"));
  assert.deepEqual(applySubtitle(spoken, chunk("a", "", true)), {
    utteranceId: "a",
    text: "That looks rough",
    done: true,
  });
});

test("a late final chunk from an interrupted utterance doesn't end the new one", () => {
  const interrupted = words("old", "That", "looks");
  const current = play(words("new", "Wait"), play(interrupted));

  const after = applySubtitle(current, chunk("old", "", true));

  assert.deepEqual(after, { utteranceId: "new", text: "Wait", done: false });
  assert.deepEqual(applySubtitle(after, chunk("new", "there")), {
    utteranceId: "new",
    text: "Wait there",
    done: false,
  });
});

test("an empty final chunk with nothing showing leaves nothing showing", () => {
  assert.equal(applySubtitle(null, chunk("a", "", true)), null);
});

test("a word from a new utterance replaces the old line", () => {
  const old = play(words("old", "That", "looks", "rough"));
  assert.deepEqual(applySubtitle(old, chunk("new", "Careful")), {
    utteranceId: "new",
    text: "Careful",
    done: false,
  });
});

test("a new utterance replaces a line that had already finished", () => {
  const finished = applySubtitle(null, chunk("old", "All done.", true));
  assert.deepEqual(applySubtitle(finished, chunk("new", "Careful")), {
    utteranceId: "new",
    text: "Careful",
    done: false,
  });
});

test("a chunk with no final flag counts as not final", () => {
  // The flag is optional in the protocol, because the brain's model gives it a default.
  const line = applySubtitle(null, { utterance_id: "a", text: "That" });
  assert.equal(line?.done, false);
});

test("applying a chunk leaves the line it was given unchanged", () => {
  // React keeps the previous value as state, so this has to return a new line.
  const line = Object.freeze({ utteranceId: "a", text: "That", done: false });
  applySubtitle(line, chunk("a", "looks"));
  applySubtitle(line, chunk("a", "", true));
  assert.deepEqual(line, { utteranceId: "a", text: "That", done: false });
});

test("a line that arrives finished is still seen before it fades", () => {
  // Subtitles-only mode sends this every time. Hiding the line outright, or fading it with a
  // transition, leaves it invisible, because a transition doesn't run on an element's first render.
  const css = readFileSync(
    new URL("../companion.css", import.meta.url),
    "utf-8",
  );
  const rule = /\.subtitles-done\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";
  assert.match(rule, /animation:/);
  assert.doesNotMatch(rule, /opacity:/);
});

test("a line that stopped growing without a final chunk is ended", () => {
  const line: SubtitleLine = {
    utteranceId: "a",
    text: "Heads up",
    done: false,
  };
  assert.deepEqual(endStaleSubtitle(line, "a"), { ...line, done: true });
});

test("ending a stale line leaves a newer or finished line alone", () => {
  const newer: SubtitleLine = { utteranceId: "b", text: "Next", done: false };
  assert.equal(endStaleSubtitle(newer, "a"), newer);
  const finished: SubtitleLine = { utteranceId: "a", text: "Done", done: true };
  assert.equal(endStaleSubtitle(finished, "a"), finished);
  assert.equal(endStaleSubtitle(null, "a"), null);
});
