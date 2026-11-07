import { app } from "electron";
import { logger } from "../lib/logger.ts";
import { installPageGuards } from "./pageGuard.ts";
import { createOverlayWindow } from "./window.ts";

if (!app.requestSingleInstanceLock()) {
  logger.warn("Overlay is already running");
  app.quit();
} else {
  app
    .whenReady()
    .then(() => {
      installPageGuards();
      createOverlayWindow();
    })
    .catch((error: unknown) => {
      logger.error("Overlay failed to start", error);
      app.quit();
    });

  app.on("window-all-closed", () => app.quit());
}
