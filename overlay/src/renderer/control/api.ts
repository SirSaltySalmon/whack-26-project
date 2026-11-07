import type { KeyList, ProcessSnapshot } from "../../lib/controlBridge.ts";
import type { KeyName, LauncherConfig } from "../../lib/launcher.ts";
import type {
  BrainDescription,
  BrainStatus,
  Control,
  ControlReply,
  Settings,
  VoiceOption,
} from "../../lib/protocol.generated.ts";
import type { SettingsChoices } from "../shared/SettingsFields.tsx";

type WithoutId<M> = M extends { request_id: string }
  ? Omit<M, "request_id">
  : never;
/** A request the brain answers; the context adds its request_id. */
export type Askable = WithoutId<Control>;
export type ReplyType = NonNullable<ControlReply["type"]>;
export type ReplyOf<T extends ReplyType> = Extract<ControlReply, { type?: T }>;

/** Everything a tab may use, from `useControl()`. Tabs never touch window.control or the socket. */
export interface ControlApi {
  process: ProcessSnapshot;
  connected: boolean;
  /** Connected to a brain this window didn't start, such as one run from a terminal. */
  external: boolean;
  status: BrainStatus | null;
  description: BrainDescription | null;
  describeError: string | null;
  refreshDescription(): void;
  config: LauncherConfig;
  /** For launch options, which apply on the next start. */
  updateConfig(change: (config: LauncherConfig) => LauncherConfig): void;
  /** Live from the brain when connected, otherwise what will be sent when it connects. */
  choices: SettingsChoices;
  changeSettings(settings: Settings): void;
  /** Every voice on offer: VOICE_OPTIONS from .env, then ones added here. */
  voices: VoiceOption[];
  keys: KeyList;
  /** Keys saved here or found in .env. */
  availableKeys: ReadonlySet<KeyName>;
  setKey(name: KeyName, value: string): Promise<void>;
  clearKey(name: KeyName): Promise<void>;
  /** Keys or launch options changed since the running brain started. */
  restartNeeded: boolean;
  start(): void;
  stop(): void;
  send(message: Control): void;
  request<T extends ReplyType>(
    message: Askable,
    expect: T,
  ): Promise<ReplyOf<T>>;
  /** Messages the brain sends unasked, such as memory toasts. */
  onPush(listener: (message: ControlReply) => void): () => void;
  logs: string[];
  typeTurn(text: string): void;
}
