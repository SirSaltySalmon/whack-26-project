/** All in Electron DIPs, relative to the overlay window, which covers the game's monitor. */
export interface Size {
  width: number;
  height: number;
}

export interface Frame extends Size {
  x: number;
  y: number;
}

export interface SizeLimits {
  minWidth: number;
  minHeight: number;
  /** Width divided by height. When set, resizing keeps this shape. */
  aspect?: number;
}

export const AVATAR_ASPECT = 3 / 4;
export const AVATAR_LIMITS: SizeLimits = {
  minWidth: 75,
  minHeight: 100,
  aspect: AVATAR_ASPECT,
};
export const WEB_CARD_LIMITS: SizeLimits = { minWidth: 320, minHeight: 240 };
export const TEXT_CARD_LIMITS: SizeLimits = { minWidth: 220, minHeight: 120 };

const clamp = (value: number, min: number, max: number): number =>
  Math.min(Math.max(value, min), Math.max(min, max));

/** Keeps a frame fully on screen, so nothing can be lost off an edge. */
export function clampFrame(frame: Frame, viewport: Size): Frame {
  const width = Math.min(frame.width, viewport.width);
  const height = Math.min(frame.height, viewport.height);
  return {
    width,
    height,
    x: clamp(frame.x, 0, viewport.width - width),
    y: clamp(frame.y, 0, viewport.height - height),
  };
}

export function moveFrame(
  frame: Frame,
  dx: number,
  dy: number,
  viewport: Size,
): Frame {
  return clampFrame({ ...frame, x: frame.x + dx, y: frame.y + dy }, viewport);
}

/** Resizes from the bottom-right corner, so the top-left stays put. */
export function resizeFrame(
  frame: Frame,
  dx: number,
  dy: number,
  viewport: Size,
  limits: SizeLimits,
): Frame {
  const maxWidth = viewport.width - frame.x;
  const maxHeight = viewport.height - frame.y;
  if (limits.aspect === undefined) {
    return {
      ...frame,
      width: clamp(frame.width + dx, limits.minWidth, maxWidth),
      height: clamp(frame.height + dy, limits.minHeight, maxHeight),
    };
  }
  const { aspect } = limits;
  // Follow whichever direction the player dragged further.
  const wanted = Math.max(frame.width + dx, (frame.height + dy) * aspect);
  const largest = Math.min(maxWidth, maxHeight * aspect);
  const width = clamp(wanted, limits.minWidth, largest);
  return { ...frame, width, height: width / aspect };
}

export function defaultAvatarFrame(viewport: Size): Frame {
  const height = 200;
  const margin = 24;
  return clampFrame(
    {
      x: margin,
      y: viewport.height - height - margin,
      width: height * AVATAR_ASPECT,
      height,
    },
    viewport,
  );
}

export function defaultWebFrame(viewport: Size): Frame {
  const width = 520;
  const height = 680;
  return clampFrame(
    { x: viewport.width - width - 24, y: 96, width, height },
    viewport,
  );
}

/** Cascades, so a stack of text cards doesn't hide the ones underneath. */
export function defaultTextFrame(viewport: Size, stackIndex: number): Frame {
  const step = stackIndex * 28;
  return clampFrame(
    { x: viewport.width - 364 - step, y: 96 + step, width: 340, height: 220 },
    viewport,
  );
}

export interface QuestionPlacement {
  left: number;
  bottom: number;
}

const QUESTION_WIDTH = 300; // Keep equal to .question's width in companion.css.
const QUESTION_GAP = 12;

/** Beside the character, on whichever side has room, so it reads as the character asking. */
export function questionPlacement(
  avatar: Frame,
  viewport: Size,
): QuestionPlacement {
  const right = avatar.x + avatar.width + QUESTION_GAP;
  const fitsRight = right + QUESTION_WIDTH <= viewport.width;
  return {
    left: fitsRight
      ? right
      : Math.max(0, avatar.x - QUESTION_GAP - QUESTION_WIDTH),
    bottom: Math.max(0, viewport.height - avatar.y - avatar.height),
  };
}

const TAB_SIZE: Size = { width: 180, height: 32 };
const TAB_GAP = 8;

/** Where the minimized wiki window sits: above the character, or below if there's no room. */
export function minimizedTabPosition(
  avatar: Frame,
  viewport: Size,
): { x: number; y: number } {
  const above = avatar.y - TAB_SIZE.height - TAB_GAP;
  const y = above >= 0 ? above : avatar.y + avatar.height + TAB_GAP;
  return clampFrame({ ...TAB_SIZE, x: avatar.x, y }, viewport);
}
