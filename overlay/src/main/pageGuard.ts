import { app, session, type WebContents } from "electron";
import { logger } from "../lib/logger.ts";
import { isWebUrl, WEB_PARTITION } from "../lib/web.ts";

/**
 * The wiki window loads arbitrary sites, because links stay in the window wherever they go. This
 * sandbox is the protection, so it's enforced here and not trusted to the renderer's markup.
 */
export function installPageGuards(): void {
  const pages = session.fromPartition(WEB_PARTITION);
  pages.setPermissionRequestHandler((_contents, permission, respond) => {
    logger.info(`Denied page permission: ${permission}`);
    respond(false);
  });
  pages.setPermissionCheckHandler(() => false);
  pages.on("will-download", (event, item) => {
    logger.info(`Blocked page download: ${item.getFilename()}`);
    event.preventDefault();
  });

  app.on("web-contents-created", (_event, contents) => {
    if (contents.getType() === "webview") {
      guardPage(contents);
    } else {
      guardApp(contents);
    }
  });
}

function guardApp(contents: WebContents): void {
  contents.on("will-attach-webview", (event, webPreferences, params) => {
    if (params.partition !== WEB_PARTITION || !isWebUrl(params.src ?? "")) {
      logger.warn(`Refused webview: ${params.src}`);
      event.preventDefault();
      return;
    }
    delete webPreferences.preload;
    webPreferences.nodeIntegration = false;
    webPreferences.contextIsolation = true;
    webPreferences.sandbox = true;
  });
  // The overlay itself never navigates or opens windows, whatever a bug in it might try.
  contents.on("will-navigate", (event, url) => {
    logger.warn(`Blocked overlay navigation: ${url}`);
    event.preventDefault();
  });
  contents.setWindowOpenHandler(() => ({ action: "deny" }));
}

function guardPage(contents: WebContents): void {
  // Links that would open a new window load in this one, so the player stays in the wiki window.
  contents.setWindowOpenHandler(({ url }) => {
    if (isWebUrl(url)) {
      contents
        .loadURL(url)
        .catch((error: unknown) => logger.warn(`Could not open ${url}`, error));
    }
    return { action: "deny" };
  });
  contents.on("will-navigate", (event, url) => {
    if (!isWebUrl(url)) {
      logger.info(`Blocked page navigation: ${url}`);
      event.preventDefault();
    }
  });
}
