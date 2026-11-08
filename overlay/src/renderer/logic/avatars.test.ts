import assert from "node:assert/strict";
import { test } from "node:test";
import {
  CAT_ID,
  CIRCLE_ID,
  cleanName,
  DEFAULT_AVATAR_ID,
  effectiveChoice,
  isUploadedAvatar,
  lookFor,
  MAX_NAME_LENGTH,
  nameFromFile,
  needsRecut,
  parseChoice,
  PNG_DATA_URL,
  sortUploads,
  uniqueName,
  type UploadedAvatar,
} from "./avatars.ts";

const CAT_SRC = "/assets/avatar-cat.png";

function upload(id: string, createdAt = 1): UploadedAvatar {
  return {
    id,
    name: `Upload ${id}`,
    createdAt,
    removeBackground: true,
    mirrored: false,
    source: `${PNG_DATA_URL}c291cmNl`,
    image: `${PNG_DATA_URL}aW1hZ2U=`,
  };
}

test("the circle is the default", () => {
  assert.equal(DEFAULT_AVATAR_ID, CIRCLE_ID);
  assert.equal(parseChoice(null), CIRCLE_ID);
  assert.equal(parseChoice(""), CIRCLE_ID);
  assert.equal(parseChoice(42), CIRCLE_ID);
  assert.equal(parseChoice("x".repeat(101)), CIRCLE_ID);
  assert.equal(parseChoice(CAT_ID), CAT_ID);
  assert.equal(parseChoice("abc-123"), "abc-123");
});

test("built-ins draw without waiting for uploads to load", () => {
  assert.deepEqual(lookFor(CIRCLE_ID, null, CAT_SRC), { kind: "circle" });
  assert.deepEqual(lookFor(CAT_ID, null, CAT_SRC), {
    kind: "image",
    src: CAT_SRC,
  });
});

test("a chosen upload waits for loading, then shows its cut-out", () => {
  const mine = upload("mine");
  assert.deepEqual(lookFor("mine", null, CAT_SRC), { kind: "loading" });
  assert.deepEqual(lookFor("mine", [mine], CAT_SRC), {
    kind: "image",
    src: mine.image,
  });
});

test("a deleted upload falls back to the circle", () => {
  assert.equal(effectiveChoice("gone", null), "gone");
  assert.equal(effectiveChoice("gone", [upload("other")]), CIRCLE_ID);
  assert.equal(effectiveChoice(CAT_ID, []), CAT_ID);
  assert.deepEqual(lookFor("gone", [], CAT_SRC), { kind: "circle" });
});

test("stored records must be our own PNGs", () => {
  assert.ok(isUploadedAvatar(upload("ok")));
  assert.ok(!isUploadedAvatar(null));
  assert.ok(!isUploadedAvatar({ ...upload("x"), image: "https://evil/x.png" }));
  assert.ok(
    !isUploadedAvatar({ ...upload("x"), source: "data:image/svg+xml,<svg/>" }),
  );
  assert.ok(!isUploadedAvatar({ ...upload("x"), mirrored: "yes" }));
  // A record can't take over a built-in's id.
  assert.ok(!isUploadedAvatar(upload(CIRCLE_ID)));
});

test("names are tidied and kept short", () => {
  assert.equal(cleanName("  my   cat  "), "my cat");
  assert.equal(cleanName("   "), "Avatar");
  assert.equal(cleanName("", "Old name"), "Old name");
  assert.equal(cleanName("x".repeat(80)).length, MAX_NAME_LENGTH);
  assert.equal(nameFromFile("my_cat-art.final.png"), "my cat art.final");
  assert.equal(nameFromFile(".png"), "Avatar");
});

test("new names don't repeat an existing one or a built-in's", () => {
  assert.equal(uniqueName("Hero", []), "Hero");
  assert.equal(uniqueName("Hero", ["hero"]), "Hero 2");
  assert.equal(uniqueName("Hero", ["Hero", "Hero 2"]), "Hero 3");
  assert.equal(uniqueName("Cat", []), "Cat 2");
  const long = "x".repeat(MAX_NAME_LENGTH);
  const next = uniqueName(long, [long]);
  assert.equal(next.length, MAX_NAME_LENGTH);
  assert.ok(next.endsWith(" 2"));
});

test("uploads sort oldest first", () => {
  const sorted = sortUploads([upload("b", 2), upload("a", 1), upload("c", 3)]);
  assert.deepEqual(
    sorted.map((avatar) => avatar.id),
    ["a", "b", "c"],
  );
});

test("only cut-out changes re-cut the picture", () => {
  const edits = { removeBackground: true, mirrored: false };
  assert.ok(!needsRecut(edits, { ...edits }));
  assert.ok(needsRecut(edits, { ...edits, mirrored: true }));
  assert.ok(needsRecut(edits, { ...edits, removeBackground: false }));
});
