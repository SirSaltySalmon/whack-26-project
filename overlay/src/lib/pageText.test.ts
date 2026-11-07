import assert from "node:assert/strict";
import { test } from "node:test";
import {
  MAX_PAGE_CHARS,
  MAX_VISIBLE_CHARS,
  READ_PAGE_SCRIPT,
  toPageText,
  withTimeout,
} from "./pageText.ts";

const URL = "https://terraria.wiki.gg/wiki/Skeletron";

test("a well-formed result keeps the main process's url and title", () => {
  const page = toPageText(
    {
      text: "All",
      visible_text: "Some",
      truncated: false,
      url: "https://evil.example/",
    },
    URL,
    "Skeletron",
  );
  assert.deepEqual(page, {
    url: URL,
    title: "Skeletron",
    text: "All",
    visible_text: "Some",
    truncated: false,
  });
});

test("results that aren't the script's shape are refused", () => {
  for (const bad of [
    null,
    undefined,
    "text",
    3,
    [],
    { text: 1, visible_text: "" },
    { text: "" },
  ]) {
    assert.equal(toPageText(bad, URL, "T"), null);
  }
});

test("text is cut to the protocol's limits and marked truncated", () => {
  const page = toPageText(
    {
      text: "a".repeat(MAX_PAGE_CHARS + 5),
      visible_text: "b".repeat(MAX_VISIBLE_CHARS + 5),
      truncated: "yes",
    },
    URL,
    "",
  );
  assert.ok(page);
  assert.equal(page.text.length, MAX_PAGE_CHARS);
  assert.equal(page.visible_text.length, MAX_VISIBLE_CHARS);
  assert.equal(page.truncated, true);
  assert.equal(page.title, null);
});

test("the read script is a single expression with the limits filled in", () => {
  assert.match(READ_PAGE_SCRIPT, /^\(\(\) => \{/);
  assert.ok(READ_PAGE_SCRIPT.includes(`slice(0, ${MAX_PAGE_CHARS})`));
  assert.ok(READ_PAGE_SCRIPT.includes(`slice(0, ${MAX_VISIBLE_CHARS})`));
  assert.ok(READ_PAGE_SCRIPT.includes('join("\\n")'));
});

test("a slow read resolves to null, and a fast one to its value", async () => {
  const never = new Promise<string>(() => {});
  assert.equal(await withTimeout(never, 10), null);
  assert.equal(await withTimeout(Promise.resolve("done"), 50), "done");
  await assert.rejects(
    withTimeout(Promise.reject(new Error("boom")), 50),
    /boom/,
  );
});
