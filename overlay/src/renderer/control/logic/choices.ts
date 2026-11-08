import type { KeyList } from "../../../lib/controlBridge.ts";
import type { KeyName, LauncherConfig } from "../../../lib/launcher.ts";
import type {
  BrainDescription,
  SettingsState,
  VoiceOption,
} from "../../../lib/protocol.generated.ts";
import type { SettingsChoices } from "../../shared/SettingsFields.tsx";

/** Keys saved here, plus any the brain reports set, such as from .env. */
export function availableKeys(
  keys: KeyList,
  description: BrainDescription | null,
): Set<KeyName> {
  const available = new Set<KeyName>(
    keys.keys.filter((key) => key.saved).map((key) => key.name),
  );
  for (const [name, set] of Object.entries(description?.keys_set ?? {})) {
    if (set) available.add(name as KeyName);
  }
  return available;
}

/** What the settings fields offer: the running brain's own lists while connected, else the
 * saved settings with what `--describe` found. */
export function settingsChoices(
  config: LauncherConfig,
  live: SettingsState | null,
  connected: boolean,
  description: BrainDescription | null,
  voices: VoiceOption[],
): SettingsChoices {
  if (connected && live) {
    return {
      settings: live.settings,
      personalities: live.personalities ?? [],
      voices: live.voices ?? [],
    };
  }
  return {
    settings: config.settings,
    personalities: description?.personalities ?? [config.settings.personality],
    voices,
  };
}
