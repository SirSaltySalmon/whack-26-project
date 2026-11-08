import type { AvatarEdits } from "../logic/avatars.ts";
import { contentBounds, removeBackground } from "../logic/background.ts";

/** Big enough for a crisp avatar, small enough to keep many of them. */
export const AVATAR_MAX_EDGE_PX = 512;
const MAX_FILE_BYTES = 20 * 1024 * 1024;
/** Room around the cut-out so soft edges and animations aren't clipped. */
const CROP_PADDING_PX = 4;

/** A problem the player can act on. Its message is fit to show them as it is. */
export class AvatarImageError extends Error {}

function canvasOf(width: number, height: number) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (context === null) {
    throw new AvatarImageError("Images can't be edited here.");
  }
  return { canvas, context };
}

/**
 * Reads a picked file into the PNG data URL kept as the avatar's original: scaled to fit
 * `AVATAR_MAX_EDGE_PX`, otherwise untouched, so every later edit starts from the same picture.
 */
export async function readAvatarSource(file: File): Promise<string> {
  if (!file.type.startsWith("image/")) {
    throw new AvatarImageError("That file isn't an image.");
  }
  if (file.size > MAX_FILE_BYTES) {
    throw new AvatarImageError("That image is too big. Pick one under 20 MB.");
  }

  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new AvatarImageError("That image couldn't be read.");
  }
  const scale = Math.min(
    1,
    AVATAR_MAX_EDGE_PX / Math.max(bitmap.width, bitmap.height),
  );
  const width = Math.max(1, Math.round(bitmap.width * scale));
  const height = Math.max(1, Math.round(bitmap.height * scale));
  try {
    const { canvas, context } = canvasOf(width, height);
    context.drawImage(bitmap, 0, 0, width, height);
    return canvas.toDataURL("image/png");
  } finally {
    bitmap.close();
  }
}

async function decode(src: string): Promise<HTMLImageElement> {
  const image = new Image();
  image.src = src;
  try {
    await image.decode();
  } catch {
    throw new AvatarImageError("That image couldn't be read.");
  }
  return image;
}

/**
 * Turns an original from `readAvatarSource` into the PNG the avatar shows: mirrored if asked,
 * optionally with its plain light background made transparent, then cropped to the character.
 */
export async function renderAvatar(
  source: string,
  edits: AvatarEdits,
): Promise<string> {
  const image = await decode(source);
  const width = image.naturalWidth;
  const height = image.naturalHeight;
  const { canvas, context } = canvasOf(width, height);
  if (edits.mirrored) {
    context.translate(width, 0);
    context.scale(-1, 1);
  }
  context.drawImage(image, 0, 0);

  // getImageData and putImageData ignore the mirror transform, so they see the result as drawn.
  const pixels = context.getImageData(0, 0, width, height);
  if (edits.removeBackground) removeBackground(pixels.data, width, height);
  const bounds = contentBounds(pixels.data, width, height, CROP_PADDING_PX);
  if (bounds === null) {
    throw new AvatarImageError(
      edits.removeBackground
        ? "Nothing was left after removing the background. Try with that option off."
        : "That image is fully transparent.",
    );
  }
  context.putImageData(pixels, 0, 0);

  const cropped = canvasOf(bounds.width, bounds.height);
  cropped.context.drawImage(
    canvas,
    bounds.x,
    bounds.y,
    bounds.width,
    bounds.height,
    0,
    0,
    bounds.width,
    bounds.height,
  );
  return cropped.canvas.toDataURL("image/png");
}
