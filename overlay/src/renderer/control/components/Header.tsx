import { useControl } from "../ControlContext.tsx";
import {
  liveCapabilities,
  predictCapabilities,
} from "../logic/capabilities.ts";
import { Pill } from "./ui.tsx";

function processLabel(control: ReturnType<typeof useControl>): {
  text: string;
  tone: "on" | "off" | "warn" | "info";
} {
  const { process, connected, external } = control;
  if (external)
    return { text: "Connected to a brain started elsewhere", tone: "info" };
  switch (process.state) {
    case "starting":
      return { text: "Starting…", tone: "warn" };
    case "running":
      return connected
        ? { text: "Running", tone: "on" }
        : { text: "Running, connecting…", tone: "warn" };
    case "stopping":
      return { text: "Stopping…", tone: "warn" };
    case "crashed":
      return {
        text: `Stopped unexpectedly${process.exitCode === null ? "" : ` (code ${process.exitCode})`}`,
        tone: "warn",
      };
    default:
      return { text: "Not running", tone: "off" };
  }
}

/** The top of the sidebar: which game, and what the partner can do. */
export function Header() {
  const control = useControl();
  const { connected, status, config } = control;
  const capabilities =
    connected && status
      ? liveCapabilities(status)
      : predictCapabilities({
          keys: control.availableKeys,
          voiceChosen: Boolean(config.settings.voice_id),
          gameTitle: config.gameTitle || control.description?.game_title || "",
          replay: config.mode === "replay",
        });
  const game = status?.game_title ?? (config.gameTitle || "No game set");
  const replay = status?.mode === "replay" ? " · replay" : "";

  return (
    <header className="cc-header">
      <div className="cc-brand">
        <span className="cc-logo" aria-hidden />
        <div>
          <h1>Control Center</h1>
          <span className="cc-subtitle" title={game + replay}>
            {game}
            {replay}
          </span>
        </div>
      </div>

      <div className="cc-capabilities" aria-label="What the partner can do">
        {capabilities.map((capability) => (
          <Pill
            key={capability.id}
            tone={capability.on ? "on" : "off"}
            title={
              capability.on ? capability.detail : `Off: ${capability.detail}`
            }
          >
            {capability.label}
          </Pill>
        ))}
      </div>
    </header>
  );
}

/** The foot of the sidebar: whether the brain runs, and the one button that changes that. */
export function RunControls() {
  const control = useControl();
  const { process, external, config } = control;
  const started = process.state !== "stopped" && process.state !== "crashed";
  const label = processLabel(control);
  const cantStart = config.mode === "replay" && !config.replayDir.trim();

  return (
    <div className="cc-run">
      <Pill tone={label.tone}>{label.text}</Pill>
      {started || external ? (
        <button
          className="cc-button cc-button-stop"
          type="button"
          disabled={process.state === "stopping"}
          onClick={control.stop}
        >
          Stop
        </button>
      ) : (
        <button
          className="cc-button cc-button-primary"
          type="button"
          disabled={cantStart}
          title={
            cantStart ? "Pick a recorded session in Agent first" : undefined
          }
          onClick={control.start}
        >
          Start partner
        </button>
      )}
    </div>
  );
}
