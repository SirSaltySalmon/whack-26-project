import assert from "node:assert/strict";
import { test } from "node:test";
import { CHAT_MAX_CHARS, chatKey, playerText } from "./chat.ts";

test("a typed turn is trimmed and sent as player.text", () => {
  assert.deepEqual(playerText("  what's that boss?  "), {
    type: "player.text",
    text: "what's that boss?",
  });
});

test("an empty or blank draft sends nothing", () => {
  assert.equal(playerText(""), null);
  assert.equal(playerText(" \n\t "), null);
});

test("a long draft is cut to the protocol's limit", () => {
  const turn = playerText("a".repeat(CHAT_MAX_CHARS + 20));
  assert.equal(turn?.text.length, CHAT_MAX_CHARS);
});

test("the limit counts characters, so an emoji at the cut isn't split in half", () => {
  const face = "\u{1F600}"; // Two UTF-16 units, one character.
  const turn = playerText("a".repeat(CHAT_MAX_CHARS - 1) + face + face);
  // A UTF-16 cut would keep half of the first face, a lone surrogate.
  assert.equal(turn?.text, "a".repeat(CHAT_MAX_CHARS - 1) + face);
});

test("a cut that ends on spaces doesn't send them", () => {
  const turn = playerText("a".repeat(CHAT_MAX_CHARS - 2) + "    tail");
  assert.equal(turn?.text, "a".repeat(CHAT_MAX_CHARS - 2));
});

test("Enter sends what was typed", () => {
  assert.deepEqual(chatKey("Enter", " hi "), {
    action: "send",
    turn: { type: "player.text", text: "hi" },
  });
});

test("Enter on an empty box closes it, so the game gets its keys back", () => {
  assert.deepEqual(chatKey("Enter", "   "), { action: "close" });
});

test("Escape closes, even with a draft", () => {
  assert.deepEqual(chatKey("Escape", "half a thought"), { action: "close" });
});

test("other keys just type", () => {
  assert.equal(chatKey("a", ""), null);
  assert.equal(chatKey("Tab", "hi"), null);
});
