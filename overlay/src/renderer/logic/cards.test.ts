import assert from "node:assert/strict";
import { test } from "node:test";
import { cardsReducer, type Card, type ShowCard } from "./cards.ts";

const FRAME = { x: 1, y: 2, width: 300, height: 400 };

const text = (id: string): ShowCard => ({
  id,
  title: id,
  body: "text",
  pageUrl: null,
  frame: FRAME,
});

const web = (id: string, pageUrl: string): ShowCard => ({
  id,
  title: id,
  body: "fallback",
  pageUrl,
  frame: FRAME,
});

const showAll = (...shown: ShowCard[]): Card[] =>
  shown.reduce<Card[]>(
    (cards, card) => cardsReducer(cards, { kind: "show", card }),
    [],
  );

test("text cards stack", () => {
  assert.deepEqual(
    showAll(text("a"), text("b")).map((card) => card.id),
    ["a", "b"],
  );
});

test("a new page reuses the one wiki window and keeps where the player put it", () => {
  const moved = { x: 50, y: 60, width: 500, height: 600 };
  let cards = showAll(web("first", "https://a.example/"));
  cards = cardsReducer(cards, { kind: "frame", id: "first", frame: moved });
  cards = cardsReducer(cards, {
    kind: "show",
    card: web("second", "https://b.example/"),
  });

  assert.equal(cards.length, 1);
  assert.equal(cards[0]?.id, "second");
  assert.deepEqual(cards[0]?.frame, moved);
  assert.equal(cards[0]?.page?.requestedUrl, "https://b.example/");
});

test("asking for the same page again navigates back to it", () => {
  const first = showAll(web("w", "https://a.example/"))[0]?.page?.requestSeq;
  const second = showAll(
    web("w", "https://a.example/"),
    web("w", "https://a.example/"),
  )[0]?.page?.requestSeq;
  assert.equal(first, 1);
  assert.equal(second, 2);
});

test("showing a page restores a minimized window", () => {
  let cards = showAll(web("w", "https://a.example/"));
  cards = cardsReducer(cards, { kind: "minimize", id: "w", minimized: true });
  assert.equal(cards[0]?.minimized, true);
  cards = cardsReducer(cards, {
    kind: "show",
    card: web("w", "https://b.example/"),
  });
  assert.equal(cards[0]?.minimized, false);
});

test("a text card never takes over the wiki window", () => {
  const cards = showAll(web("w", "https://a.example/"), text("note"));
  assert.equal(cards.length, 2);
  assert.notEqual(cards.find((card) => card.id === "w")?.page, null);
});

test("re-showing a wiki window without a URL keeps its page", () => {
  const cards = showAll(web("w", "https://a.example/"), text("w"));
  assert.equal(cards[0]?.page?.requestedUrl, "https://a.example/");
});

test("raising puts a card on top without reordering, which would reload a webview", () => {
  let cards = showAll(text("a"), text("b"));
  cards = cardsReducer(cards, { kind: "raise", id: "a" });
  assert.deepEqual(
    cards.map((card) => card.id),
    ["a", "b"],
  );
  const z = (id: string) => cards.find((card) => card.id === id)?.z ?? -1;
  assert.ok(z("a") > z("b"));
  assert.equal(cardsReducer(cards, { kind: "raise", id: "a" }), cards);
});

test("showing a page again keeps the window's place in the array", () => {
  let cards = showAll(web("w", "https://a.example/"), text("note"));
  cards = cardsReducer(cards, {
    kind: "show",
    card: web("w2", "https://b.example/"),
  });
  assert.deepEqual(
    cards.map((card) => card.id),
    ["w2", "note"],
  );
  assert.ok((cards[0]?.z ?? -1) > (cards[1]?.z ?? -1));
});

test("closing removes only that card", () => {
  let cards = showAll(text("a"), text("b"));
  cards = cardsReducer(cards, { kind: "close", id: "b" });
  assert.deepEqual(
    cards.map((card) => card.id),
    ["a"],
  );
});

test("navigation records the page, and a later title doesn't lose the URL", () => {
  let cards = showAll(web("w", "https://a.example/"));
  cards = cardsReducer(cards, {
    kind: "navigated",
    id: "w",
    url: "https://c.example/",
  });
  cards = cardsReducer(cards, {
    kind: "navigated",
    id: "w",
    url: "https://c.example/",
    title: "C",
  });
  assert.equal(cards[0]?.page?.currentUrl, "https://c.example/");
  assert.equal(cards[0]?.page?.pageTitle, "C");
});

test("updates and actions on unknown cards change nothing", () => {
  const cards = showAll(text("a"));
  assert.deepEqual(cardsReducer(cards, { kind: "close", id: "nope" }), cards);
  assert.deepEqual(
    cardsReducer(cards, { kind: "update", id: "nope", title: "x" }),
    cards,
  );
  assert.equal(
    cardsReducer(cards, { kind: "update", id: "a", title: "x" })[0]?.title,
    "x",
  );
});
