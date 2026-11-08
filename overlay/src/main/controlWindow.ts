import { join } from "node:path";
import {
  BrowserWindow,
  ipcMain,
  type IpcMainEvent,
  type IpcMainInvokeEvent,
} from "electron";
import { CONTROL_IPC, isMemoryRequest } from "../lib/controlBridge.ts";
import { isKeyName } from "../lib/launcher.ts";
import { logger } from "../lib/logger.ts";
import {
  BrainProcess,
  describeBrain,
  pythonFor,
  repoRoot,
} from "./brainProcess.ts";
import { ConfigStore } from "./configStore.ts";
import { MemoryReader } from "./memoryReader.ts";
import { KeyStore } from "./secrets.ts";

export interface ControlCenter {
  window: BrowserWindow;
  brain: BrainProcess;
}

/**
 * The launcher: a normal window, unlike the overlay, because typing keys needs keyboard focus.
 * It is never always-on-top and never focuses itself, so it can't take the game's keyboard.
 */
export function createControlWindow(): ControlCenter {
  const win = new BrowserWindow({
    width: 1180,
    height: 760,
    minWidth: 860,
    minHeight: 560,
    show: false,
    title: "Control Center",
    backgroundColor: "#0e1016",
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, "../preload/control.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webviewTag: false,
    },
  });
  win.once("ready-to-show", () => win.show());

  const brain = new BrainProcess();
  wireIpc(win, brain);

  const devUrl = process.env["ELECTRON_RENDERER_URL"];
  const loaded = devUrl
    ? win.loadURL(`${devUrl}/control.html`)
    : win.loadFile(join(__dirname, "../renderer/control.html"));
  loaded.catch((error: unknown) =>
    logger.error("Control Center failed to load", error),
  );
  return { window: win, brain };
}

function wireIpc(win: BrowserWindow, brain: BrainProcess): void {
  const config = new ConfigStore();
  const keys = new KeyStore();
  const memory = new MemoryReader(() => ({
    python: pythonFor(config.get()),
    cwd: repoRoot(),
  }));
  const ours = (event: IpcMainInvokeEvent | IpcMainEvent): boolean =>
    event.sender === win.webContents;

  // Every handler checks the sender, so no other page can start processes or touch keys.
  const handle = (
    channel: string,
    run: (...args: unknown[]) => unknown,
  ): void => {
    ipcMain.handle(channel, (event, ...args: unknown[]) => {
      if (!ours(event)) throw new Error("Only the Control Center may ask this");
      return run(...args);
    });
  };

  handle(CONTROL_IPC.getConfig, () => config.get());
  handle(CONTROL_IPC.setConfig, (raw) => config.set(raw));
  handle(CONTROL_IPC.listKeys, () => keys.list());
  handle(CONTROL_IPC.setKey, (name, value) =>
    isKeyName(name) && typeof value === "string"
      ? keys.set(name, value)
      : keys.list(),
  );
  handle(CONTROL_IPC.clearKey, (name) =>
    isKeyName(name) ? keys.clear(name) : keys.list(),
  );
  handle(CONTROL_IPC.describe, () => describeBrain(config.get()));
  handle(CONTROL_IPC.memory, (request) =>
    isMemoryRequest(request)
      ? memory.ask(request)
      : { ok: false, error: "Not a memory request" },
  );
  handle(CONTROL_IPC.start, async () => {
    const current = config.get();
    // Voices from .env are kept when the player adds their own, so ask what .env offers.
    const described = current.customVoices.length
      ? await describeBrain(current)
      : null;
    const envVoices = described?.ok ? described.description.voices : [];
    return brain.start(current, keys.values(), envVoices);
  });
  handle(CONTROL_IPC.stop, () => brain.stop());
  handle(CONTROL_IPC.getProcess, () => brain.current);
  handle(CONTROL_IPC.getLogs, () => brain.logs);
  ipcMain.on(CONTROL_IPC.typeTurn, (event, text: unknown) => {
    if (ours(event) && typeof text === "string") brain.type(text);
  });

  const toWindow = (channel: string, value: unknown): void => {
    if (!win.isDestroyed()) win.webContents.send(channel, value);
  };
  brain.onChange = (snapshot) => toWindow(CONTROL_IPC.process, snapshot);
  brain.onLines = (lines) => toWindow(CONTROL_IPC.logs, lines);

  win.on("closed", () => {
    memory.stop();
    for (const channel of Object.values(CONTROL_IPC)) {
      ipcMain.removeHandler(channel);
      ipcMain.removeAllListeners(channel);
    }
  });
}
