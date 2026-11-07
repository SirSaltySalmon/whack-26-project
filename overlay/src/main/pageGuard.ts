import { app, session, type WebContents } from "electron";
import { logger } from "../lib/logger.ts";
import {
  type PageText,
  READ_PAGE_SCRIPT,
  READ_TIMEOUT_MS,
  READ_WORLD_ID,
  toPageText,
  withTimeout,
} from "../lib/pageText.ts";
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

/** The wiki window's page. There's only one wiki window, so the newest webview is the one. */
let openPage: WebContents | null = null;

/**
 * Reads the open page's rendered text in our own isolated world, so the page's scripts can't
 * tamper with the reader. Resolves to null, with the reason logged, rather than ever throwing.
 */
export async function readOpenPage(): Promise<PageText | null> {
  const contents = openPage;
  if (contents === null || contents.isDestroyed()) {
    logger.info("No page to read: the wiki window isn't open");
    return null;
  }
  try {
    const result: unknown = await withTimeout(
      contents.executeJavaScriptInIsolatedWorld(READ_WORLD_ID, [
        { code: READ_PAGE_SCRIPT },
      ]),
      READ_TIMEOUT_MS,
    );
    if (result === null) {
      logger.warn(`Page read timed out after ${READ_TIMEOUT_MS} ms`);
      return null;
    }
    // Taken now, not when the read was asked for, so the brain can check the host it came from.
    const page = toPageText(result, contents.getURL(), contents.getTitle());
    if (page === null) logger.warn("Page read returned something unexpected");
    return page;
  } catch (error: unknown) {
    logger.warn("Page read failed", error);
    return null;
  }
}

function guardPage(contents: WebContents): void {
  openPage = contents;
  contents.once("destroyed", () => {
    if (openPage === contents) openPage = null;
  });
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
