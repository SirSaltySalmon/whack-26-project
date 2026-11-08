import { contextBridge, ipcRenderer, type IpcRendererEvent } from "electron";
import {
  CONTROL_IPC,
  type ControlBridge,
  type ProcessSnapshot,
} from "../lib/controlBridge.ts";

function listen<T>(channel: string, listener: (value: T) => void): () => void {
  const wrapped = (_event: IpcRendererEvent, value: T): void => listener(value);
  ipcRenderer.on(channel, wrapped);
  return () => ipcRenderer.off(channel, wrapped);
}

const bridge: ControlBridge = {
  manageMemory: (request) =>
    ipcRenderer.invoke(CONTROL_IPC.manageMemory, request),
  getConfig: () => ipcRenderer.invoke(CONTROL_IPC.getConfig),
  setConfig: (config) => ipcRenderer.invoke(CONTROL_IPC.setConfig, config),
  listKeys: () => ipcRenderer.invoke(CONTROL_IPC.listKeys),
  setKey: (name, value) => ipcRenderer.invoke(CONTROL_IPC.setKey, name, value),
  clearKey: (name) => ipcRenderer.invoke(CONTROL_IPC.clearKey, name),
  describe: () => ipcRenderer.invoke(CONTROL_IPC.describe),
  memory: (request) => ipcRenderer.invoke(CONTROL_IPC.memory, request),
  start: () => ipcRenderer.invoke(CONTROL_IPC.start),
  stop: () => ipcRenderer.invoke(CONTROL_IPC.stop),
  getProcess: () => ipcRenderer.invoke(CONTROL_IPC.getProcess),
  getLogs: () => ipcRenderer.invoke(CONTROL_IPC.getLogs),
  typeTurn: (text) => ipcRenderer.send(CONTROL_IPC.typeTurn, text),
  onProcess: (listener) =>
    listen<ProcessSnapshot>(CONTROL_IPC.process, listener),
  onLogs: (listener) => listen<string[]>(CONTROL_IPC.logs, listener),
};

contextBridge.exposeInMainWorld("control", bridge);
