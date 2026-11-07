import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { app, safeStorage } from "electron";
import type { KeyList, KeyStatus } from "../lib/controlBridge.ts";
import { isKeyName, KEY_NAMES, type KeyName } from "../lib/launcher.ts";
import { logger } from "../lib/logger.ts";

/**
 * API keys typed into the Control Center. Encrypted with the OS (DPAPI on Windows) and only ever
 * decrypted to hand to the brain's environment. The window only sees whether each one is set.
 */
export class KeyStore {
  private readonly path = join(app.getPath("userData"), "keys.json");

  list(): KeyList {
    const stored = this.read();
    const keys: KeyStatus[] = KEY_NAMES.map((name) => {
      const value = stored[name] ? this.decrypt(name, stored[name]) : null;
      return {
        name,
        saved: value !== null,
        hint: value ? hintFor(value) : null,
      };
    });
    return { keys, canEncrypt: safeStorage.isEncryptionAvailable() };
  }

  set(name: KeyName, value: string): KeyList {
    const trimmed = value.trim();
    if (!isKeyName(name) || !trimmed) return this.list();
    if (!safeStorage.isEncryptionAvailable()) {
      logger.warn(
        "Can't encrypt keys on this machine; put them in .env instead",
      );
      return this.list();
    }
    const stored = this.read();
    stored[name] = safeStorage.encryptString(trimmed).toString("base64");
    this.write(stored);
    logger.info(`Saved ${name}`);
    return this.list();
  }

  clear(name: KeyName): KeyList {
    if (!isKeyName(name)) return this.list();
    const stored = this.read();
    delete stored[name];
    this.write(stored);
    logger.info(`Removed ${name}`);
    return this.list();
  }

  /** For the brain's environment only. Never send this to a renderer. */
  values(): Partial<Record<KeyName, string>> {
    const stored = this.read();
    const values: Partial<Record<KeyName, string>> = {};
    for (const name of KEY_NAMES) {
      const blob = stored[name];
      const value = blob ? this.decrypt(name, blob) : null;
      if (value) values[name] = value;
    }
    return values;
  }

  private decrypt(name: KeyName, blob: string): string | null {
    try {
      return safeStorage.decryptString(Buffer.from(blob, "base64"));
    } catch (error) {
      // Happens if the file came from another Windows account; the player can enter it again.
      logger.warn(`Could not decrypt the saved ${name}`, error);
      return null;
    }
  }

  private read(): Partial<Record<KeyName, string>> {
    try {
      const parsed: unknown = JSON.parse(readFileSync(this.path, "utf-8"));
      if (typeof parsed !== "object" || parsed === null) return {};
      const entries = Object.entries(parsed).filter(
        (entry): entry is [KeyName, string] =>
          isKeyName(entry[0]) && typeof entry[1] === "string",
      );
      return Object.fromEntries(entries);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        logger.warn("Could not read saved keys", error);
      }
      return {};
    }
  }

  private write(stored: Partial<Record<KeyName, string>>): void {
    try {
      writeFileSync(this.path, JSON.stringify(stored, null, 2), "utf-8");
    } catch (error) {
      logger.error("Could not save keys", error);
    }
  }
}

function hintFor(value: string): string {
  return value.length >= 12 ? `…${value.slice(-4)}` : "set";
}
