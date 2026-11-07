import { contentBounds, removeBackground } from "../logic/background.ts";

/** Big enough for a crisp avatar, small enough to keep in local storage. */
export const AVATAR_MAX_EDGE_PX = 512;
const MAX_FILE_BYTES = 20 * 1024 * 1024;
/** Room around the cut-out so soft edges and animations aren't clipped. */
const CROP_PADDING_PX = 4;

/**
 * Turns a picked file into the PNG data URL the avatar shows: scaled down, optionally with its
 * plain light background made transparent, then cropped to the character. Throws with a message
 * fit to show the player if the file can't be used.
 */
export async function prepareAvatarImage(
  file: File,
  withoutBackground: boolean,
): Promise<string> {
  if (!file.type.startsWith("image/")) {
    throw new Error("That file isn't an image.");
  }
  if (file.size > MAX_FILE_BYTES) {
    throw new Error("That image is too big. Pick one under 20 MB.");
  }

  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new Error("That image couldn't be read.");
  }
  const scale = Math.min(
    1,
    AVATAR_MAX_EDGE_PX / Math.max(bitmap.width, bitmap.height),
  );
  const width = Math.max(1, Math.round(bitmap.width * scale));
  const height = Math.max(1, Math.round(bitmap.height * scale));

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (context === null) throw new Error("Images can't be edited here.");
  context.drawImage(bitmap, 0, 0, width, height);
  bitmap.close();

  const pixels = context.getImageData(0, 0, width, height);
  if (withoutBackground) removeBackground(pixels.data, width, height);
  const bounds = contentBounds(pixels.data, width, height, CROP_PADDING_PX);
  if (bounds === null) {
    throw new Error(
      "Nothing was left after removing the background. Try with that option off.",
    );
  }
  context.putImageData(pixels, 0, 0);

  const cropped = document.createElement("canvas");
  cropped.width = bounds.width;
  cropped.height = bounds.height;
  cropped
    .getContext("2d")
    ?.drawImage(
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
  return cropped.toDataURL("image/png");
}
