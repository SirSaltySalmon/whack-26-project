/**
 * Makes an image's plain light background transparent, so the game shows around the avatar.
 *
 * Only background reachable from the image's edges is removed, by flood fill. Deleting every white
 * pixel would punch holes in white fur, eyes and highlights inside the character. Pure, so it runs
 * the same on uploads in the renderer and on the bundled cat.
 */

export interface BackgroundOptions {
  /** A pixel is background if its darkest channel is at least this. */
  minLevel: number;
  /** ...and its channels differ by at most this, so pale colours aren't mistaken for white. */
  maxSpread: number;
  /** Pixels this close to the removed area get soft edges instead of a white fringe. */
  feather: number;
  /**
   * Within `feather` of the background, light greys down to this level go too. They're the
   * blurred rim between subject and white, and softening them leaves a grey outline instead.
   */
  edgeLevel: number;
  /** Below this darkest channel, an edge pixel keeps all of its colour. */
  featherFloor: number;
}

export const DEFAULT_BACKGROUND: BackgroundOptions = {
  minLevel: 225,
  maxSpread: 30,
  feather: 2,
  edgeLevel: 175,
  featherFloor: 150,
};

/** Treated as background already, so a transparent PNG floods the same way as a white one. */
const CLEAR_ALPHA = 16;

function isBackground(
  rgba: Uint8ClampedArray,
  pixel: number,
  options: BackgroundOptions,
  minLevel = options.minLevel,
): boolean {
  const i = pixel * 4;
  if ((rgba[i + 3] ?? 0) < CLEAR_ALPHA) return true;
  const r = rgba[i] ?? 0;
  const g = rgba[i + 1] ?? 0;
  const b = rgba[i + 2] ?? 0;
  const low = Math.min(r, g, b);
  return low >= minLevel && Math.max(r, g, b) - low <= options.maxSpread;
}

/** Steps to every pixel from `seeds`, through pixels `canEnter` allows, up to `limit` steps. */
function spread(
  width: number,
  height: number,
  seeds: number[],
  distance: Int32Array,
  canEnter: (pixel: number) => boolean,
  limit: number,
): void {
  let frontier = seeds;
  for (let step = 1; step <= limit && frontier.length > 0; step += 1) {
    const next: number[] = [];
    for (const pixel of frontier) {
      const x = pixel % width;
      const y = (pixel - x) / width;
      for (let dy = -1; dy <= 1; dy += 1) {
        for (let dx = -1; dx <= 1; dx += 1) {
          const nx = x + dx;
          const ny = y + dy;
          if (nx < 0 || ny < 0 || nx >= width || ny >= height) continue;
          const neighbour = ny * width + nx;
          if (distance[neighbour] !== -1 || !canEnter(neighbour)) continue;
          distance[neighbour] = step;
          next.push(neighbour);
        }
      }
    }
    frontier = next;
  }
}

/** Edits `rgba` in place. Returns how many pixels became fully transparent. */
export function removeBackground(
  rgba: Uint8ClampedArray,
  width: number,
  height: number,
  options: BackgroundOptions = DEFAULT_BACKGROUND,
): number {
  const count = width * height;
  if (count === 0 || rgba.length < count * 4) return 0;

  // 0 marks background, -1 unvisited, and 1..feather how far a pixel is from the background.
  const distance = new Int32Array(count).fill(-1);
  const seeds: number[] = [];
  const seed = (pixel: number): void => {
    if (distance[pixel] === -1 && isBackground(rgba, pixel, options)) {
      distance[pixel] = 0;
      seeds.push(pixel);
    }
  };
  for (let x = 0; x < width; x += 1) {
    seed(x);
    seed((height - 1) * width + x);
  }
  for (let y = 0; y < height; y += 1) {
    seed(y * width);
    seed(y * width + width - 1);
  }

  // Flood the background first, at "distance 0" throughout.
  let frontier = seeds;
  while (frontier.length > 0) {
    const next: number[] = [];
    for (const pixel of frontier) {
      const x = pixel % width;
      const y = (pixel - x) / width;
      const around = [
        x > 0 ? pixel - 1 : -1,
        x < width - 1 ? pixel + 1 : -1,
        y > 0 ? pixel - width : -1,
        y < height - 1 ? pixel + width : -1,
      ];
      for (const neighbour of around) {
        if (neighbour < 0 || distance[neighbour] !== -1) continue;
        if (!isBackground(rgba, neighbour, options)) continue;
        distance[neighbour] = 0;
        next.push(neighbour);
      }
    }
    frontier = next;
  }

  let cleared = 0;
  const background: number[] = [];
  for (let pixel = 0; pixel < count; pixel += 1) {
    if (distance[pixel] === 0) {
      rgba[pixel * 4 + 3] = 0;
      cleared += 1;
      background.push(pixel);
    }
  }

  spread(width, height, background, distance, () => true, options.feather);
  for (let pixel = 0; pixel < count; pixel += 1) {
    if ((distance[pixel] ?? 0) <= 0) continue;
    if (isBackground(rgba, pixel, options, options.edgeLevel)) {
      rgba[pixel * 4 + 3] = 0;
      cleared += 1;
    } else {
      softenEdge(rgba, pixel, options);
    }
  }
  return cleared;
}

/**
 * Edge pixels are partly mixed with the white behind them. Take the white back out: the lighter
 * the pixel, the more transparent it becomes, and its colour is unmixed from white to match.
 */
function softenEdge(
  rgba: Uint8ClampedArray,
  pixel: number,
  options: BackgroundOptions,
): void {
  const i = pixel * 4;
  const alpha = rgba[i + 3] ?? 0;
  if (alpha === 0) return;
  const low = Math.min(rgba[i] ?? 0, rgba[i + 1] ?? 0, rgba[i + 2] ?? 0);
  const whiteness = Math.min(
    1,
    Math.max(0, (low - options.featherFloor) / (255 - options.featherFloor)),
  );
  const keep = 1 - whiteness;
  if (keep >= 1) return;
  if (keep <= 0) {
    rgba[i + 3] = 0;
    return;
  }
  for (let c = 0; c < 3; c += 1) {
    const mixed = rgba[i + c] ?? 0;
    rgba[i + c] = Math.round((mixed - 255 * whiteness) / keep);
  }
  rgba[i + 3] = Math.round(alpha * keep);
}

export interface Bounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** The smallest box holding every visible pixel, plus `padding`, or null if there are none. */
export function contentBounds(
  rgba: Uint8ClampedArray,
  width: number,
  height: number,
  padding = 0,
): Bounds | null {
  let left = width;
  let top = height;
  let right = -1;
  let bottom = -1;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if ((rgba[(y * width + x) * 4 + 3] ?? 0) < CLEAR_ALPHA) continue;
      left = Math.min(left, x);
      right = Math.max(right, x);
      top = Math.min(top, y);
      bottom = Math.max(bottom, y);
    }
  }
  if (right < 0) return null;
  const x = Math.max(0, left - padding);
  const y = Math.max(0, top - padding);
  return {
    x,
    y,
    width: Math.min(width, right + padding + 1) - x,
    height: Math.min(height, bottom + padding + 1) - y,
  };
}
