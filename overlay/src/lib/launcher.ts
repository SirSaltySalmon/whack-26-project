/* What the Control Center saves between runs, and how it becomes the brain's command line and
   environment. Pure, so the main process and the window share it and tests need no Electron. */
import type {
  MemorySearch,
  Settings,
  VoiceOption,
  VoiceStyle,
} from "./protocol.generated.ts";

/** The only environment variables the Control Center will store or pass on as keys. */
export const KEY_NAMES = [
  "GEMINI_API_KEY",
  "ANTHROPIC_API_KEY",
  "DEEPGRAM_API_KEY",
  "ELEVENLABS_API_KEY",
  "EXA_API_KEY",
  "CARTESIA_API_KEY",
] as const;
export type KeyName = (typeof KEY_NAMES)[number];

export function isKeyName(value: unknown): value is KeyName {
  return (KEY_NAMES as readonly unknown[]).includes(value);
}

/** Settings with every field filled in. The generated type marks defaulted fields optional. */
export interface PartnerSettings {
  proactive: boolean;
  personality: string;
  voice_id: string | null;
  /** Kept here so "Type instead" survives a restart, and changing another setting can't undo it. */
  mic_enabled: boolean;
  voice_style: VoiceStyle;
  memory_search: MemorySearch;
}

export function partnerSettings(settings: Settings): PartnerSettings {
  return {
    proactive: settings.proactive ?? true,
    personality: settings.personality ?? DEFAULT_PERSONALITY,
    voice_id: settings.voice_id ?? null,
    mic_enabled: settings.mic_enabled ?? true,
    voice_style: settings.voice_style ?? DEFAULT_VOICE_STYLE,
    memory_search: settings.memory_search ?? DEFAULT_MEMORY_SEARCH,
  };
}

/** Matches the brain's default in shared/protocol/messages.py. */
export const DEFAULT_VOICE_STYLE: VoiceStyle = "expressive";
/** Matches the brain's default in shared/protocol/messages.py. */
export const DEFAULT_MEMORY_SEARCH: MemorySearch = "keyword";
const MEMORY_SEARCHES: readonly MemorySearch[] = [
  "keyword",
  "hybrid",
  "semantic",
];

const DEFAULT_PERSONALITY = "supportive";

export interface VoiceTuning {
  halfDuplex: boolean;
  keyterms: string[];
  micIndex: number | null;
  speakerIndex: number | null;
}

export interface LauncherConfig {
  /** Empty means the repo's own .venv. */
  pythonPath: string;
  mode: "live" | "replay";
  replayDir: string;
  gameProcess: string;
  gameTitle: string;
  typed: boolean;
  record: boolean;
  verbose: boolean;
  /** Voices added here, on top of the ones VOICE_OPTIONS in .env offers. */
  customVoices: VoiceOption[];
  tuning: VoiceTuning;
  /** Sent to the brain as soon as it connects, so the first line already uses them. */
  settings: PartnerSettings;
}

export const DEFAULT_CONFIG: LauncherConfig = {
  pythonPath: "",
  mode: "live",
  replayDir: "",
  gameProcess: "",
  gameTitle: "",
  typed: true,
  record: false,
  verbose: false,
  customVoices: [],
  tuning: {
    halfDuplex: false,
    keyterms: [],
    micIndex: null,
    speakerIndex: null,
  },
  settings: {
    proactive: true,
    personality: DEFAULT_PERSONALITY,
    voice_id: null,
    mic_enabled: true,
    voice_style: DEFAULT_VOICE_STYLE,
    memory_search: DEFAULT_MEMORY_SEARCH,
  },
};

type Loose = Record<string, unknown>;

const isObject = (value: unknown): value is Loose =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown, fallback: string): string =>
  typeof value === "string" ? value : fallback;
const flag = (value: unknown, fallback: boolean): boolean =>
  typeof value === "boolean" ? value : fallback;
const index = (value: unknown): number | null =>
  typeof value === "number" && Number.isInteger(value) && value >= 0
    ? value
    : null;

function voices(value: unknown): VoiceOption[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) =>
    isObject(item) &&
    typeof item.name === "string" &&
    typeof item.id === "string"
      ? [{ name: item.name, id: item.id }]
      : [],
  );
}

/** Saved files can be old or hand-edited, so every field falls back to its default. */
export function sanitizeConfig(raw: unknown): LauncherConfig {
  const saved = isObject(raw) ? raw : {};
  const tuning = isObject(saved.tuning) ? saved.tuning : {};
  const settings = isObject(saved.settings) ? saved.settings : {};
  const defaults = DEFAULT_CONFIG;
  return {
    pythonPath: text(saved.pythonPath, defaults.pythonPath),
    mode: saved.mode === "replay" ? "replay" : "live",
    replayDir: text(saved.replayDir, defaults.replayDir),
    gameProcess: text(saved.gameProcess, defaults.gameProcess),
    gameTitle: text(saved.gameTitle, defaults.gameTitle),
    typed: flag(saved.typed, defaults.typed),
    record: flag(saved.record, defaults.record),
    verbose: flag(saved.verbose, defaults.verbose),
    customVoices: voices(saved.customVoices),
    tuning: {
      halfDuplex: flag(tuning.halfDuplex, defaults.tuning.halfDuplex),
      keyterms: Array.isArray(tuning.keyterms)
        ? tuning.keyterms.filter(
            (term): term is string => typeof term === "string",
          )
        : [],
      micIndex: index(tuning.micIndex),
      speakerIndex: index(tuning.speakerIndex),
    },
    settings: {
      proactive: flag(settings.proactive, true),
      personality: text(settings.personality, defaults.settings.personality),
      voice_id:
        typeof settings.voice_id === "string" ? settings.voice_id : null,
      mic_enabled: flag(settings.mic_enabled, true),
      voice_style:
        settings.voice_style === "classic" ? "classic" : DEFAULT_VOICE_STYLE,
      memory_search:
        MEMORY_SEARCHES.find((mode) => mode === settings.memory_search) ??
        DEFAULT_MEMORY_SEARCH,
    },
  };
}

/** Voices offered anywhere: the ones from .env first, then ones added here, without repeats. */
export function allVoices(
  fromEnv: readonly VoiceOption[],
  custom: readonly VoiceOption[],
): VoiceOption[] {
  const seen = new Set<string>();
  return [...fromEnv, ...custom].filter((voice) => {
    if (seen.has(voice.id)) return false;
    seen.add(voice.id);
    return true;
  });
}

export function brainArgs(config: LauncherConfig): string[] {
  const args = ["-m", "brain"];
  if (config.mode === "replay") {
    args.push("--replay", config.replayDir.trim());
  } else {
    args.push("--live");
    if (config.record) args.push("--record");
  }
  if (config.typed) args.push("--type");
  if (config.verbose) args.push("--verbose");
  return args;
}

/**
 * The environment added for the brain. Values left empty are left out, so .env still applies:
 * pydantic-settings reads real environment variables before .env.
 */
export function toEnv(
  config: LauncherConfig,
  keys: Partial<Record<KeyName, string>>,
  envVoices: readonly VoiceOption[],
): Record<string, string> {
  const env: Record<string, string> = {
    // Logs reach the Control Center line by line, and the Windows console encoding can't
    // mangle names or transcripts.
    PYTHONUNBUFFERED: "1",
    PYTHONIOENCODING: "utf-8",
  };
  // Only when on: passing "false" would override VOICE_HALF_DUPLEX=true in .env, and the
  // partner would hear and interrupt itself.
  if (config.tuning.halfDuplex) env.VOICE_HALF_DUPLEX = "true";
  for (const name of KEY_NAMES) {
    const value = keys[name]?.trim();
    if (value) env[name] = value;
  }
  const put = (name: string, value: string): void => {
    if (value.trim()) env[name] = value.trim();
  };
  put("GAME_PROCESS", config.gameProcess);
  put("GAME_TITLE", config.gameTitle);
  // The voice is chosen before the brain builds its speech pipeline, which only speaks if a
  // voice is known at that moment.
  put("ELEVENLABS_VOICE_ID", config.settings.voice_id ?? "");
  if (config.customVoices.length > 0) {
    env.VOICE_OPTIONS = JSON.stringify(
      allVoices(envVoices, config.customVoices),
    );
  }
  if (config.tuning.keyterms.length > 0) {
    env.STT_KEYTERMS = JSON.stringify(config.tuning.keyterms);
  }
  if (config.tuning.micIndex !== null)
    env.MIC_DEVICE_INDEX = String(config.tuning.micIndex);
  if (config.tuning.speakerIndex !== null) {
    env.SPEAKER_DEVICE_INDEX = String(config.tuning.speakerIndex);
  }
  return env;
}
