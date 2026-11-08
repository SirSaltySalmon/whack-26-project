import { app } from "electron";
import { logger } from "../lib/logger.ts";
import { createControlWindow, type ControlCenter } from "./controlWindow.ts";
import { installPageGuards } from "./pageGuard.ts";
import { createOverlayWindow } from "./window.ts";

let control: ControlCenter | null = null;
let quitting = false;

if (!app.requestSingleInstanceLock()) {
  logger.warn("Overlay is already running");
  app.quit();
} else {
  app
    .whenReady()
    .then(() => {
      installPageGuards();
      createOverlayWindow();
      control = createControlWindow();
      // Closing the Control Center ends the session, so no brain is left running unseen.
      control.window.on("closed", () => app.quit());
    })
    .catch((error: unknown) => {
      logger.error("Overlay failed to start", error);
      app.quit();
    });

  // A second launch brings the existing Control Center forward instead of starting another.
  app.on("second-instance", () => {
    const win = control?.window;
    if (win && !win.isDestroyed()) {
      if (win.isMinimized()) win.restore();
      win.show();
    }
  });

  app.on("before-quit", (event) => {
    const brain = control?.brain;
    if (quitting || !brain?.alive) return;
    event.preventDefault();
    quitting = true;
    brain
      .stop()
      .catch((error: unknown) =>
        logger.error("Could not stop the brain", error),
      )
      .finally(() => app.quit());
  });

  app.on("window-all-closed", () => app.quit());
}
