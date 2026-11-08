import assert from "node:assert/strict";
import { test } from "node:test";
import {
  isMemoryRequest,
  type MemoryAnswer,
  type MemoryRequest,
} from "../../../lib/controlBridge.ts";
import type { Askable } from "../api.ts";
import { readMemory } from "./readMemory.ts";

const GAMES: MemoryAnswer = {
  ok: true,
  reply: {
    type: "memory.games",
    request_id: "r1",
    games: [
      {
        title: "Terraria",
        facts: 3,
        questions: 1,
        sessions: 2,
        last_played: 9,
      },
    ],
    current: "Terraria",
    live: false,
  },
};

function bridge(answer: MemoryAnswer) {
  const asked: MemoryRequest[] = [];
  return {
    asked,
    memory: (request: MemoryRequest) => {
      asked.push(request);
      return Promise.resolve(answer);
    },
  };
}

test("only memory requests can go to the reader", () => {
  assert.equal(isMemoryRequest({ type: "memory.query", text: "boss" }), true);
  assert.equal(isMemoryRequest({ type: "memory.list_games" }), true);
  assert.equal(isMemoryRequest({ type: "control.shutdown" }), false);
  assert.equal(isMemoryRequest({ type: "toString" }), false);
  assert.equal(isMemoryRequest({ type: 1 }), false);
  assert.equal(isMemoryRequest(null), false);
  assert.equal(isMemoryRequest("memory.query"), false);
});

test("with no brain, memory is read through the bridge", async () => {
  const fake = bridge(GAMES);
  const reply = await readMemory(
    fake,
    { type: "memory.list_games" },
    "memory.games",
  );
  assert.equal(reply.current, "Terraria");
  assert.deepEqual(fake.asked, [{ type: "memory.list_games" }]);
});

test("with no brain, anything but memory is refused without asking", async () => {
  const fake = bridge(GAMES);
  // Every askable request is a memory one today; this guards the next request someone adds.
  const other = { type: "voice.preview", text: "Hi" } as unknown as Askable;
  await assert.rejects(
    readMemory(fake, other, "memory.games"),
    /isn't connected/,
  );
  assert.deepEqual(fake.asked, []);
});

test("reader errors and mismatched replies reject", async () => {
  await assert.rejects(
    readMemory(
      bridge({ ok: false, error: "Could not run Python: ENOENT" }),
      { type: "memory.list_games" },
      "memory.games",
    ),
    /Could not run Python/,
  );
  await assert.rejects(
    readMemory(
      bridge(GAMES),
      { type: "memory.query", text: "x" },
      "memory.results",
    ),
    /Expected memory.results, got memory.games/,
  );
});
