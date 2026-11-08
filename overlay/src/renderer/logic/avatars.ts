/**
 * Which avatar the partner wears. Pure, so the overlay, the Control Center and the tests share it.
 *
 * Built-ins ship with the app. Uploads live in IndexedDB (`lib/avatarStore.ts`) under random ids,
 * so they can't collide with a built-in's id.
 */

export const CIRCLE_ID = "circle";
export const CAT_ID = "cat";
export const DEFAULT_AVATAR_ID = CIRCLE_ID;

export const BUILT_IN_AVATARS: readonly { id: string; name: string }[] = [
  { id: CIRCLE_ID, name: "Circle" },
  { id: CAT_ID, name: "Cat" },
];

/** Only PNGs we made ourselves, so a tampered record can't point the avatar at anything else. */
export const PNG_DATA_URL = "data:image/png;base64,";
export const MAX_NAME_LENGTH = 40;
const FALLBACK_NAME = "Avatar";

/** How an upload is cut from its original. Changing one re-cuts the picture. */
export interface AvatarEdits {
  removeBackground: boolean;
  mirrored: boolean;
}

export interface UploadedAvatar extends AvatarEdits {
  id: string;
  name: string;
  createdAt: number;
  /** The picked image, scaled down but otherwise untouched, so every edit can be undone. */
  source: string;
  /** What the overlay shows: `source` with the edits applied, cropped to the character. */
  image: string;
}

export type AvatarLook =
  { kind: "loading" } | { kind: "circle" } | { kind: "image"; src: string };

const isBuiltIn = (id: string): boolean =>
  BUILT_IN_AVATARS.some((avatar) => avatar.id === id);

export function isUploadedAvatar(value: unknown): value is UploadedAvatar {
  if (typeof value !== "object" || value === null) return false;
  const avatar = value as Record<string, unknown>;
  return (
    typeof avatar["id"] === "string" &&
    avatar["id"] !== "" &&
    !isBuiltIn(avatar["id"]) &&
    typeof avatar["name"] === "string" &&
    Number.isFinite(avatar["createdAt"]) &&
    typeof avatar["removeBackground"] === "boolean" &&
    typeof avatar["mirrored"] === "boolean" &&
    typeof avatar["source"] === "string" &&
    avatar["source"].startsWith(PNG_DATA_URL) &&
    typeof avatar["image"] === "string" &&
    avatar["image"].startsWith(PNG_DATA_URL)
  );
}

/** A saved choice, or the default if there's none or it isn't usable. */
export function parseChoice(raw: unknown): string {
  return typeof raw === "string" && raw !== "" && raw.length <= 100
    ? raw
    : DEFAULT_AVATAR_ID;
}

/**
 * The choice that's really in effect. An upload deleted from the other window, or lost with
 * cleared storage, falls back to the default. `uploads` is null until they've loaded.
 */
export function effectiveChoice(
  choice: string,
  uploads: readonly UploadedAvatar[] | null,
): string {
  if (isBuiltIn(choice) || uploads === null) return choice;
  return uploads.some((avatar) => avatar.id === choice)
    ? choice
    : DEFAULT_AVATAR_ID;
}

/** What the overlay draws. `catSrc` is passed in because only the bundler can resolve it. */
export function lookFor(
  choice: string,
  uploads: readonly UploadedAvatar[] | null,
  catSrc: string,
): AvatarLook {
  const id = effectiveChoice(choice, uploads);
  if (id === CIRCLE_ID) return { kind: "circle" };
  if (id === CAT_ID) return { kind: "image", src: catSrc };
  const upload = uploads?.find((avatar) => avatar.id === id);
  // Not loaded yet. Drawing the circle meanwhile would flash it on every start.
  return upload ? { kind: "image", src: upload.image } : { kind: "loading" };
}

/** Collapses whitespace and trims to the length the gallery can show. */
export function cleanName(text: string, fallback = FALLBACK_NAME): string {
  const name = text.replace(/\s+/g, " ").trim().slice(0, MAX_NAME_LENGTH);
  return name.trim() || fallback;
}

/** "my_cat-art.png" becomes "my cat art". */
export function nameFromFile(fileName: string): string {
  return cleanName(fileName.replace(/\.[^.]*$/, "").replace(/[_-]+/g, " "));
}

/** `base`, or `base 2`, `base 3`... whichever no other avatar has. Ignores case. */
export function uniqueName(base: string, taken: Iterable<string>): string {
  const used = new Set([...taken].map((name) => name.toLowerCase()));
  for (const avatar of BUILT_IN_AVATARS) used.add(avatar.name.toLowerCase());
  if (!used.has(base.toLowerCase())) return base;
  for (let n = 2; ; n += 1) {
    const suffix = ` ${n}`;
    const name = base.slice(0, MAX_NAME_LENGTH - suffix.length) + suffix;
    if (!used.has(name.toLowerCase())) return name;
  }
}

/** Oldest first, so a new upload lands at the end of the gallery. */
export function sortUploads(
  uploads: readonly UploadedAvatar[],
): UploadedAvatar[] {
  return [...uploads].sort((a, b) => a.createdAt - b.createdAt);
}

export function needsRecut(before: AvatarEdits, after: AvatarEdits): boolean {
  return (
    before.removeBackground !== after.removeBackground ||
    before.mirrored !== after.mirrored
  );
}
