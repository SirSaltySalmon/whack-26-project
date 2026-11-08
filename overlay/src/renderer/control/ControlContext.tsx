import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { KeyList, ProcessSnapshot } from "../../lib/controlBridge.ts";
import {
  allVoices,
  partnerSettings,
  type KeyName,
  type LauncherConfig,
} from "../../lib/launcher.ts";
import { logger } from "../../lib/logger.ts";
import type {
  BrainDescription,
  BrainStatus,
  Control,
  ControlReply,
  SettingsState,
} from "../../lib/protocol.generated.ts";
import { PROTOCOL_VERSION } from "../lib/brainSocket.ts";
import { brainUrl, JsonSocket } from "../lib/jsonSocket.ts";
import type { ControlApi, ReplyOf } from "./api.ts";
import { RequestTracker } from "./logic/requests.ts";

export type { Askable, ControlApi, ReplyOf, ReplyType } from "./api.ts";

const MAX_LOGS = 2000;
const STOPPED: ProcessSnapshot = {
  state: "stopped",
  pid: null,
  exitCode: null,
  startedAt: null,
  startedWithKeys: [],
};

const ControlContext = createContext<ControlApi | null>(null);

export function useControl(): ControlApi {
  const api = useContext(ControlContext);
  if (!api)
    throw new Error("useControl() must be used inside <ControlProvider>");
  return api;
}

export function ControlProvider({ children }: { children: ReactNode }) {
  const bridge = window.control;
  const [config, setConfig] = useState<LauncherConfig | null>(null);
  const [proc, setProcess] = useState<ProcessSnapshot>(STOPPED);
  const [keys, setKeys] = useState<KeyList>({ keys: [], canEncrypt: true });
  const [description, setDescription] = useState<BrainDescription | null>(null);
  const [describeError, setDescribeError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState<BrainStatus | null>(null);
  const [live, setLive] = useState<SettingsState | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [changedAt, setChangedAt] = useState(0);

  const socket = useRef<JsonSocket<ControlReply, Control> | null>(null);
  const requests = useRef(new RequestTracker());
  const pushListeners = useRef(new Set<(message: ControlReply) => void>());
  const latest = useRef({ config, proc });
  latest.current = { config, proc };

  const save = useCallback(
    (next: LauncherConfig) => {
      bridge
        .setConfig(next)
        .catch((error: unknown) => logger.error("Could not save", error));
    },
    [bridge],
  );

  const refreshDescription = useCallback(() => {
    setDescribeError(null);
    bridge
      .describe()
      .then((result) => {
        if (result.ok) setDescription(result.description);
        else setDescribeError(result.error);
      })
      .catch((error: unknown) => setDescribeError(String(error)));
  }, [bridge]);

  useEffect(() => {
    bridge
      .getConfig()
      .then(setConfig, (e: unknown) => logger.error("No config", e));
    bridge.listKeys().then(setKeys, (e: unknown) => logger.error("No keys", e));
    bridge
      .getProcess()
      .then(setProcess, (e: unknown) => logger.error("No process", e));
    bridge.getLogs().then(setLogs, (e: unknown) => logger.error("No logs", e));
    refreshDescription();
    const offProcess = bridge.onProcess(setProcess);
    const offLogs = bridge.onLogs((lines) =>
      setLogs((current) => [...current, ...lines].slice(-MAX_LOGS)),
    );
    return () => {
      offProcess();
      offLogs();
    };
  }, [bridge, refreshDescription]);

  useEffect(() => {
    const link = new JsonSocket<ControlReply, Control>(brainUrl("/control"), {
      onOpen: () => {
        setConnected(true);
        link.send({
          type: "control.hello",
          protocol_version: PROTOCOL_VERSION,
        });
        // A brain we started gets the choices made here before it started.
        const { config: saved, proc: running } = latest.current;
        if (
          saved &&
          running.state !== "stopped" &&
          running.state !== "crashed"
        ) {
          link.send({ type: "settings.update", settings: saved.settings });
        }
      },
      onMessage: (message) => {
        if (requests.current.settle(message)) return;
        if (message.type === "settings.state") {
          setLive(message);
          setConfig(
            (current) =>
              current && {
                ...current,
                settings: partnerSettings(message.settings),
              },
          );
        } else if (message.type === "brain.status") {
          setStatus(message);
        }
        for (const listener of pushListeners.current) listener(message);
      },
      onClose: () => {
        setConnected(false);
        setStatus(null);
        setLive(null);
        requests.current.failAll("The brain disconnected");
      },
    });
    socket.current = link;
    return () => link.close();
  }, []);

  // Saved after every change, including settings the brain echoes back.
  useEffect(() => {
    if (config) save(config);
  }, [config, save]);

  // Stable for the window's life, so tabs can list them as effect dependencies.
  const send = useCallback(
    (message: Control): void => socket.current?.send(message),
    [],
  );
  const request = useCallback<ControlApi["request"]>(
    async (message, expect) => {
      if (!socket.current?.connected)
        throw new Error("The brain isn't connected");
      const { id, reply } = requests.current.open(expect);
      send({ ...message, request_id: id } as Control);
      return (await reply) as ReplyOf<typeof expect>;
    },
    [send],
  );
  const onPush = useCallback<ControlApi["onPush"]>((listener) => {
    pushListeners.current.add(listener);
    return () => pushListeners.current.delete(listener);
  }, []);

  const api = useMemo<ControlApi | null>(() => {
    if (!config) return null;
    const started = proc.state !== "stopped" && proc.state !== "crashed";
    const voices = allVoices(description?.voices ?? [], config.customVoices);
    const available = new Set<KeyName>(
      keys.keys.filter((key) => key.saved).map((key) => key.name),
    );
    for (const [name, set] of Object.entries(description?.keys_set ?? {})) {
      if (set) available.add(name as KeyName);
    }
    return {
      process: proc,
      connected,
      external: connected && !started,
      status,
      description,
      describeError,
      refreshDescription,
      config,
      updateConfig: (change) => {
        setConfig((current) => current && change(current));
        setChangedAt(Date.now());
      },
      choices:
        connected && live
          ? {
              settings: live.settings,
              personalities: live.personalities ?? [],
              voices: live.voices ?? [],
            }
          : {
              settings: config.settings,
              personalities: description?.personalities ?? [
                config.settings.personality,
              ],
              voices,
            },
      changeSettings: (settings) => {
        setConfig(
          (current) =>
            current && { ...current, settings: partnerSettings(settings) },
        );
        if (connected) send({ type: "settings.update", settings });
      },
      voices,
      keys,
      availableKeys: available,
      setKey: async (name, value) => {
        setKeys(await bridge.setKey(name, value));
        setChangedAt(Date.now());
      },
      clearKey: async (name) => {
        setKeys(await bridge.clearKey(name));
        setChangedAt(Date.now());
      },
      restartNeeded: started && changedAt > (proc.startedAt ?? Infinity),
      start: () => {
        bridge
          .start()
          .then(setProcess, (e: unknown) => logger.error("Start failed", e));
      },
      stop: () => {
        if (connected && !started) {
          send({ type: "control.shutdown" });
          return;
        }
        bridge
          .stop()
          .then(setProcess, (e: unknown) => logger.error("Stop failed", e));
      },
      send,
      request,
      onPush,
      logs,
      typeTurn: (text) => bridge.typeTurn(text),
    };
  }, [
    bridge,
    config,
    proc,
    connected,
    status,
    description,
    describeError,
    refreshDescription,
    live,
    keys,
    changedAt,
    logs,
    send,
    request,
    onPush,
  ]);

  if (!api) return <p className="cc-loading">Loading the Control Center…</p>;
  return (
    <ControlContext.Provider value={api}>{children}</ControlContext.Provider>
  );
}
