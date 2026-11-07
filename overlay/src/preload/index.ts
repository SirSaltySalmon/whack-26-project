import { contextBridge, ipcRenderer } from "electron";
import {
  IPC_READ_PAGE,
  IPC_REQUEST_TYPING,
  IPC_SET_MOUSE_CAPTURE,
  type OverlayBridge,
} from "../lib/bridge.ts";

const bridge: OverlayBridge = {
  setMouseCapture: (capture) =>
    ipcRenderer.send(IPC_SET_MOUSE_CAPTURE, capture),
  requestTyping: () => ipcRenderer.send(IPC_REQUEST_TYPING),
  readPage: () => ipcRenderer.invoke(IPC_READ_PAGE),
};

contextBridge.exposeInMainWorld("overlay", bridge);
