import {
  DEFAULT_MEMORY_SEARCH,
  DEFAULT_VOICE_STYLE,
} from "../../lib/launcher.ts";
import type {
  MemorySearch,
  Settings,
  VoiceOption,
  VoiceStyle,
} from "../../lib/protocol.generated.ts";
import { Dropdown, type DropdownOption } from "./Dropdown.tsx";

type OnOff = "on" | "off";

const HINT_CHOICES: readonly DropdownOption<OnOff>[] = [
  { value: "on", label: "Offer hints" },
  { value: "off", label: "Just chat" },
];

const MIC_CHOICES: readonly DropdownOption<OnOff>[] = [
  { value: "on", label: "Listen" },
  { value: "off", label: "Type instead" },
];

const VOICE_STYLE_CHOICES: readonly DropdownOption<VoiceStyle>[] = [
  { value: "expressive", label: "Expressive" },
  { value: "classic", label: "Classic" },
];

const MEMORY_SEARCH_CHOICES: readonly DropdownOption<MemorySearch>[] = [
  { value: "keyword", label: "Keywords" },
  { value: "hybrid", label: "Both" },
  { value: "semantic", label: "Meaning" },
];

export interface SettingsChoices {
  settings: Settings;
  personalities: string[];
  voices: VoiceOption[];
}

interface SettingsFieldsProps {
  choices: SettingsChoices;
  onChange(settings: Settings): void;
}

export function Choice({
  label,
  on,
  onClick,
}: {
  label: string;
  on: boolean;
  onClick(): void;
}) {
  return (
    <button
      className={`option${on ? " option-on" : ""}`}
      type="button"
      aria-pressed={on}
      onClick={onClick}
    >
      {label}
    </button>
  );
}

/**
 * Dropdowns built from buttons, so changing a setting in the overlay never takes the keyboard
 * from the game. Shared by the overlay's settings card and the Control Center's Agent tab.
 */
export function SettingsFields({ choices, onChange }: SettingsFieldsProps) {
  const { settings, personalities, voices } = choices;
  const proactive = settings.proactive ?? true;
  const micEnabled = settings.mic_enabled ?? true;
  const style = settings.voice_style ?? DEFAULT_VOICE_STYLE;
  const memorySearch = settings.memory_search ?? DEFAULT_MEMORY_SEARCH;
  return (
    <>
      <h3 className="settings-heading">Hints</h3>
      <div className="settings-row">
        <Dropdown
          label="Hints"
          value={proactive ? "on" : "off"}
          options={HINT_CHOICES}
          onChange={(hints) =>
            onChange({ ...settings, proactive: hints === "on" })
          }
        />
      </div>
      {/* Off, the partner still watches and talks; the player answers in the overlay's text box. */}
      <h3 className="settings-heading">Microphone</h3>
      <div className="settings-row">
        <Dropdown
          label="Microphone"
          value={micEnabled ? "on" : "off"}
          options={MIC_CHOICES}
          onChange={(mic) =>
            onChange({ ...settings, mic_enabled: mic === "on" })
          }
        />
      </div>
      <h3 className="settings-heading">Personality</h3>
      <div className="settings-row">
        <Dropdown
          label="Personality"
          value={settings.personality}
          options={personalities.map((name) => ({ value: name, label: name }))}
          onChange={(personality) => onChange({ ...settings, personality })}
        />
      </div>
      {voices.length > 0 && (
        <>
          <h3 className="settings-heading">Voice</h3>
          <div className="settings-row">
            <Dropdown
              label="Voice"
              value={settings.voice_id}
              options={voices.map((voice) => ({
                value: voice.id,
                label: voice.name,
              }))}
              onChange={(voice_id) => onChange({ ...settings, voice_id })}
            />
          </div>
        </>
      )}
      <h3 className="settings-heading">Voice tone</h3>
      <div className="settings-row">
        <Dropdown
          label="Voice tone"
          value={style}
          options={VOICE_STYLE_CHOICES}
          onChange={(voice_style) => onChange({ ...settings, voice_style })}
        />
      </div>
      <h3 className="settings-heading">Memory search</h3>
      <div className="settings-row">
        <Dropdown
          label="Memory search"
          value={memorySearch}
          options={MEMORY_SEARCH_CHOICES}
          onChange={(memory_search) => onChange({ ...settings, memory_search })}
        />
      </div>
      <p className="settings-hint">
        How the partner finds what it remembers about your words. Meaning also
        catches different wording, like "house" for "base", using a small local
        model that loads in the background. Both uses keywords and meaning.
      </p>
    </>
  );
}
