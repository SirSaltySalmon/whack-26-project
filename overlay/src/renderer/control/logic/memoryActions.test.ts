import assert from "node:assert/strict";
import { test } from "node:test";
import type { MemoryAdminResult } from "../../../lib/protocol.generated.ts";
import { MemoryActions } from "./memoryActions.ts";

const empty: MemoryAdminResult = {
  facts: [],
  total_facts: 0,
  notes: 0,
  events: 0,
  questions: 0,
  database: "test.db",
};

test("an in-flight forget cannot be overtaken by an old refresh", async () => {
  const actions = new MemoryActions();
  let finish!: (result: MemoryAdminResult) => void;
  const pending = new Promise<MemoryAdminResult>((resolve) => {
    finish = resolve;
  });
  const forgetting = actions.run(
    { operation: "forget", fact_id: 7 },
    () => pending,
  );
  let refreshed = false;
  assert.equal(
    await actions.run({ operation: "list" }, async () => {
      refreshed = true;
      return empty;
    }),
    null,
  );
  assert.equal(refreshed, false);
  finish(empty);
  assert.deepEqual(await forgetting, empty);
  assert.equal(actions.busy, false);
  assert.deepEqual(
    await actions.run({ operation: "list" }, async () => empty),
    empty,
  );
});

test("a failed forget cannot be reported as success, and can be retried", async () => {
  const actions = new MemoryActions();
  const unchanged: MemoryAdminResult = {
    ...empty,
    total_facts: 1,
    facts: [
      {
        id: 7,
        game: "Game",
        subject: "player",
        attribute: "goal",
        value: "explore",
        source: "player",
        confidence: 1,
        tentative: false,
        valid_from: 1,
      },
    ],
  };
  await assert.rejects(
    actions.run({ operation: "forget", fact_id: 7 }, async () => unchanged),
    /not saved/,
  );
  assert.equal(actions.busy, false);
  await assert.rejects(
    actions.run({ operation: "forget", fact_id: 7 }, async () => {
      throw new Error("database locked");
    }),
    /database locked/,
  );
  assert.equal(actions.busy, false);
  assert.deepEqual(
    await actions.run({ operation: "forget", fact_id: 7 }, async () => empty),
    empty,
  );
});
