/**
 * The overlay's looks. Each is a stylesheet in `skins/` scoped by `data-skin` on the root element,
 * so a skin is data: adding one is a file and a line here, never a branch in a component.
 */
export const SKINS = [
  {
    id: "sticker",
    label: "Sticker",
    hint: "Thick outlines, hard shadows and loud colour.",
  },
  {
    id: "island",
    label: "Island",
    hint: "Tinted glass and a black pill for each line.",
  },
  {
    id: "signal",
    label: "Signal",
    hint: "Monochrome hardware with dot-matrix type.",
  },
  {
    id: "pixel",
    label: "Pixel",
    hint: "Dialogue boxes that suit 2D pixel-art games.",
  },
  {
    id: "broadcast",
    label: "Broadcast",
    hint: "Esports lower thirds and italic caps.",
  },
  {
    id: "classic",
    label: "Classic",
    hint: "The original plain look.",
  },
] as const;

export type SkinId = (typeof SKINS)[number]["id"];

export const DEFAULT_SKIN: SkinId = "sticker";

/** A saved value from another version, or a tampered one, falls back to the default. */
export function parseSkin(value: unknown): SkinId {
  return SKINS.find((skin) => skin.id === value)?.id ?? DEFAULT_SKIN;
}
