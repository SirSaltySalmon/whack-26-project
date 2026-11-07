import { logger } from "../../lib/logger.ts";
import type { Frame } from "../logic/layout.ts";

/** Where the player put things. Only a convenience, so failures log and fall back to defaults. */
function read(key: string): unknown {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? null : (JSON.parse(raw) as unknown);
  } catch (error) {
    logger.warn(`Could not read saved ${key}`, error);
    return null;
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (error) {
    logger.warn(`Could not save ${key}`, error);
  }
}

function isFrame(value: unknown): value is Frame {
  if (typeof value !== "object" || value === null) return false;
  const frame = value as Record<string, unknown>;
  return ["x", "y", "width", "height"].every((key) =>
    Number.isFinite(frame[key]),
  );
}

function frameStore(key: string) {
  return {
    load(): Frame | null {
      const value = read(key);
      return isFrame(value) ? value : null;
    },
    save(frame: Frame): void {
      write(key, frame);
    },
  };
}

export const savedAvatarFrame = frameStore("overlay.avatarFrame");
export const savedWebFrame = frameStore("overlay.webFrame");

export const savedLastPage = {
  load(): string | null {
    const value = read("overlay.lastPage");
    return typeof value === "string" ? value : null;
  },
  save(url: string): void {
    write("overlay.lastPage", url);
  },
};
