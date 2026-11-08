import { join } from "node:path";
import { BrowserWindow, ipcMain, screen } from "electron";
import {
  IPC_END_TYPING,
  IPC_READ_PAGE,
  IPC_REQUEST_TYPING,
  IPC_SET_MOUSE_CAPTURE,
} from "../lib/bridge.ts";
import { logger } from "../lib/logger.ts";
import { readOpenPage } from "./pageGuard.ts";

function releaseMouse(win: BrowserWindow): void {
  win.setIgnoreMouseEvents(true, { forward: true });
}

export function createOverlayWindow(): BrowserWindow {
  const win = new BrowserWindow({
    ...screen.getPrimaryDisplay().bounds,
    show: false,
    frame: false,
    transparent: true,
    backgroundColor: "#00000000",
    hasShadow: false,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    // Clicking the overlay mustn't take the keyboard from the game: the player would stop moving.
    focusable: false,
    alwaysOnTop: true,
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webviewTag: true,
      // The overlay is rarely focused, and throttling would stall animations and rect reports.
      backgroundThrottling: false,
    },
  });

  // "normal" can fall behind a borderless game. Don't use setContentProtection: see CLAUDE.md.
  win.setAlwaysOnTop(true, "screen-saver");
  releaseMouse(win);
  win.once("ready-to-show", () => {
    win.showInactive();
    // Applied again because showing the window must never leave it catching the game's clicks.
    releaseMouse(win);
  });

  wireInput(win);
  wireRecovery(win);

  const devUrl = process.env["ELECTRON_RENDERER_URL"];
  const loaded = devUrl
    ? win.loadURL(devUrl)
    : win.loadFile(join(__dirname, "../renderer/index.html"));
  loaded.catch((error: unknown) =>
    logger.error("Overlay failed to load", error),
  );
  return win;
}

function wireInput(win: BrowserWindow): void {
  ipcMain.on(IPC_SET_MOUSE_CAPTURE, (event, capture: unknown) => {
    if (event.sender !== win.webContents) return;
    if (capture === true) {
      win.setIgnoreMouseEvents(false);
    } else {
      releaseMouse(win);
    }
  });

  ipcMain.on(IPC_REQUEST_TYPING, (event) => {
    if (event.sender !== win.webContents) return;
    win.setFocusable(true);
    win.focus();
  });
  ipcMain.on(IPC_END_TYPING, (event) => {
    if (event.sender !== win.webContents) return;
    // On Windows this alone drops focus, and Windows hands the foreground to the next window down,
    // which is the game while it's in front. Elsewhere it keeps focus, so blur explicitly.
    win.setFocusable(false);
    if (win.isFocused()) win.blur();
  });
  // Clicking back into the game ends typing, and the overlay goes back to never taking focus.
  win.on("blur", () => win.setFocusable(false));

  // Only the overlay may ask: a web page has no bridge, and this refuses any other sender too.
  ipcMain.handle(IPC_READ_PAGE, (event) =>
    event.sender === win.webContents ? readOpenPage() : null,
  );
}

function wireRecovery(win: BrowserWindow): void {
  // A dead renderer can't report the cursor leaving, so a window left capturing would block the
  // game's mouse until the overlay was killed.
  win.webContents.on("render-process-gone", (_event, details) => {
    logger.error(`Overlay renderer gone: ${details.reason}`);
    releaseMouse(win);
    win.reload();
  });

  win.webContents.on("console-message", ({ level, message }) => {
    if (level === "warning" || level === "error") {
      logger[level === "error" ? "error" : "warn"](`renderer: ${message}`);
    }
  });

  const fitToDisplay = (): void => {
    win.setBounds(screen.getPrimaryDisplay().bounds);
  };
  screen.on("display-metrics-changed", fitToDisplay);
  win.on("closed", () => screen.off("display-metrics-changed", fitToDisplay));
}
