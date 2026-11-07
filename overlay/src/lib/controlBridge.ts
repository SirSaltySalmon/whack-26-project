/* What the Control Center window can ask the main process to do. The overlay window and web pages
   never get this bridge: it can start processes and store keys. Kept apart from bridge.ts so the
   two sandboxed preloads share no module, which a sandboxed preload couldn't load. */
import type { KeyName, LauncherConfig } from "./launcher.ts";
import type { BrainDescription } from "./protocol.generated.ts";

export type ProcessState =
  "stopped" | "starting" | "running" | "stopping" | "crashed";

export interface ProcessSnapshot {
  state: ProcessState;
  pid: number | null;
  exitCode: number | null;
  startedAt: number | null;
  /** Which keys the running brain was started with, so the window can say when to restart. */
  startedWithKeys: KeyName[];
}

export interface KeyStatus {
  name: KeyName;
  saved: boolean;
  /** The last few characters, so the player can tell keys apart. Never the key itself. */
  hint: string | null;
}

export interface KeyList {
  keys: KeyStatus[];
  /** False when the OS can't encrypt, in which case keys belong in .env instead. */
  canEncrypt: boolean;
}

export type DescribeResult =
  { ok: true; description: BrainDescription } | { ok: false; error: string };

export interface ControlBridge {
  getConfig(): Promise<LauncherConfig>;
  setConfig(config: LauncherConfig): Promise<LauncherConfig>;
  listKeys(): Promise<KeyList>;
  setKey(name: KeyName, value: string): Promise<KeyList>;
  clearKey(name: KeyName): Promise<KeyList>;
  describe(): Promise<DescribeResult>;
  start(): Promise<ProcessSnapshot>;
  stop(): Promise<ProcessSnapshot>;
  getProcess(): Promise<ProcessSnapshot>;
  getLogs(): Promise<string[]>;
  /** One player turn for a brain started with --type. */
  typeTurn(text: string): void;
  onProcess(listener: (snapshot: ProcessSnapshot) => void): () => void;
  onLogs(listener: (lines: string[]) => void): () => void;
}

export const CONTROL_IPC = {
  getConfig: "control:get-config",
  setConfig: "control:set-config",
  listKeys: "control:list-keys",
  setKey: "control:set-key",
  clearKey: "control:clear-key",
  describe: "control:describe",
  start: "control:start",
  stop: "control:stop",
  getProcess: "control:get-process",
  getLogs: "control:get-logs",
  typeTurn: "control:type-turn",
  process: "control:process",
  logs: "control:logs",
} as const;
