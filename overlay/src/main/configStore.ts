import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { app } from "electron";
import {
  DEFAULT_CONFIG,
  sanitizeConfig,
  type LauncherConfig,
} from "../lib/launcher.ts";
import { logger } from "../lib/logger.ts";

/** The Control Center's choices, kept in the app's own folder rather than the repo. */
export class ConfigStore {
  private readonly path = join(app.getPath("userData"), "launcher.json");
  private config: LauncherConfig = this.load();

  get(): LauncherConfig {
    return this.config;
  }

  set(raw: unknown): LauncherConfig {
    this.config = sanitizeConfig(raw);
    try {
      writeFileSync(this.path, JSON.stringify(this.config, null, 2), "utf-8");
    } catch (error) {
      logger.error("Could not save the Control Center settings", error);
    }
    return this.config;
  }

  private load(): LauncherConfig {
    try {
      return sanitizeConfig(JSON.parse(readFileSync(this.path, "utf-8")));
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        logger.warn("Could not read the Control Center settings", error);
      }
      return DEFAULT_CONFIG;
    }
  }
}
