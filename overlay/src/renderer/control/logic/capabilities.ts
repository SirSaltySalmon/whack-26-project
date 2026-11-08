import type { KeyName } from "../../../lib/launcher.ts";
import type { BrainStatus } from "../../../lib/protocol.generated.ts";

export interface Capability {
  id: "watching" | "listening" | "speaking" | "talking" | "wiki";
  label: string;
  on: boolean;
  /** Why it's off, or what it runs on. */
  detail: string;
}

export interface PredictInput {
  keys: ReadonlySet<KeyName>;
  voiceChosen: boolean;
  gameTitle: string;
  replay: boolean;
}

/** What will run once started, from which keys exist. Mirrors how brain/app.py decides. */
export function predictCapabilities(input: PredictInput): Capability[] {
  const has = (name: KeyName): boolean => input.keys.has(name);
  const live = !input.replay;
  const listening = live && has("DEEPGRAM_API_KEY");
  const talking = has("GEMINI_API_KEY");
  return [
    {
      id: "watching",
      label: "Watching",
      on: live && has("ANTHROPIC_API_KEY"),
      detail: live ? "needs ANTHROPIC_API_KEY" : "off in replay",
    },
    {
      id: "listening",
      label: "Listening",
      on: listening,
      detail: live ? "needs DEEPGRAM_API_KEY" : "off in replay",
    },
    {
      id: "speaking",
      label: "Speaking",
      on: listening && has("ELEVENLABS_API_KEY") && input.voiceChosen,
      detail: "needs Deepgram, ElevenLabs and a voice",
    },
    {
      id: "talking",
      label: "Talking",
      on: talking,
      detail: "needs GEMINI_API_KEY",
    },
    {
      id: "wiki",
      label: "Wiki",
      on: live && talking && input.gameTitle.trim() !== "",
      detail: "needs GEMINI_API_KEY and a game title",
    },
  ];
}

/** What is really running, from the brain's own report. */
export function liveCapabilities(status: BrainStatus): Capability[] {
  const running = "running";
  return [
    { id: "watching", label: "Watching", on: status.watching, detail: running },
    {
      id: "listening",
      label: "Listening",
      on: status.listening,
      detail: running,
    },
    { id: "speaking", label: "Speaking", on: status.speaking, detail: running },
    { id: "talking", label: "Talking", on: status.talking, detail: running },
    {
      id: "wiki",
      label: "Wiki",
      on: status.wiki_url !== null && status.wiki_url !== undefined,
      detail: status.wiki_url ?? "not found yet",
    },
  ];
}
