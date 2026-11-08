import { logger } from "../../lib/logger.ts";
import { parseChoice, PNG_DATA_URL } from "../logic/avatars.ts";
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

/** A built-in's id or an upload's. The uploads themselves are in `avatarStore.ts`. */
export const savedAvatarChoice = {
  load(): string {
    return parseChoice(read("overlay.avatarChoice"));
  },
  save(id: string): void {
    write("overlay.avatarChoice", id);
  },
};

/**
 * Before the gallery, one uploaded picture lived here. It's read once, moved into the gallery,
 * then cleared. Only PNGs we made ourselves, so a tampered value can't point anywhere else.
 */
export const legacyAvatarImage = {
  load(): string | null {
    const value = read("overlay.avatarImage");
    return typeof value === "string" && value.startsWith(PNG_DATA_URL)
      ? value
      : null;
  },
  clear(): void {
    try {
      localStorage.removeItem("overlay.avatarImage");
    } catch (error) {
      logger.warn("Could not clear the old avatar image", error);
    }
  },
};

/** Whether new uploads get their white background removed. */
export const savedRemoveBackground = {
  load(): boolean {
    return read("overlay.removeBackground") !== false;
  },
  save(remove: boolean): void {
    write("overlay.removeBackground", remove);
  },
};

export const savedLastPage = {
  load(): string | null {
    const value = read("overlay.lastPage");
    return typeof value === "string" ? value : null;
  },
  save(url: string): void {
    write("overlay.lastPage", url);
  },
};
