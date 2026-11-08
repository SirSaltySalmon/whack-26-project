import {
  DEFAULT_MEMORY_SEARCH,
  DEFAULT_VOICE_STYLE,
} from "../../lib/launcher.ts";
import type {
  MemorySearch,
  Settings,
  VoiceOption,
} from "../../lib/protocol.generated.ts";

const MEMORY_SEARCH_CHOICES: readonly { mode: MemorySearch; label: string }[] =
  [
    { mode: "keyword", label: "Keywords" },
    { mode: "hybrid", label: "Both" },
    { mode: "semantic", label: "Meaning" },
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
 * Buttons only, so changing a setting in the overlay never takes the keyboard from the game.
 * Shared by the overlay's settings card and the Control Center's Agent tab.
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
        <Choice
          label="Offer hints"
          on={proactive}
          onClick={() => onChange({ ...settings, proactive: true })}
        />
        <Choice
          label="Just chat"
          on={!proactive}
          onClick={() => onChange({ ...settings, proactive: false })}
        />
      </div>
      {/* Off, the partner still watches and talks; the player answers in the overlay's text box. */}
      <h3 className="settings-heading">Microphone</h3>
      <div className="settings-row">
        <Choice
          label="Listen"
          on={micEnabled}
          onClick={() => onChange({ ...settings, mic_enabled: true })}
        />
        <Choice
          label="Type instead"
          on={!micEnabled}
          onClick={() => onChange({ ...settings, mic_enabled: false })}
        />
      </div>
      <h3 className="settings-heading">Personality</h3>
      <div className="settings-row">
        {personalities.map((name) => (
          <Choice
            key={name}
            label={name}
            on={settings.personality === name}
            onClick={() => onChange({ ...settings, personality: name })}
          />
        ))}
      </div>
      {voices.length > 0 && (
        <>
          <h3 className="settings-heading">Voice</h3>
          <div className="settings-row">
            {voices.map((voice) => (
              <Choice
                key={voice.id}
                label={voice.name}
                on={settings.voice_id === voice.id}
                onClick={() => onChange({ ...settings, voice_id: voice.id })}
              />
            ))}
          </div>
        </>
      )}
      <h3 className="settings-heading">Voice tone</h3>
      <div className="settings-row">
        <Choice
          label="Expressive"
          on={style === "expressive"}
          onClick={() => onChange({ ...settings, voice_style: "expressive" })}
        />
        <Choice
          label="Classic"
          on={style === "classic"}
          onClick={() => onChange({ ...settings, voice_style: "classic" })}
        />
      </div>
      <p className="settings-hint">
        Expressive varies pitch and pace with what's said. Classic is the
        original steadier voice. Applies from the next line.
      </p>
      <h3 className="settings-heading">Memory search</h3>
      <div className="settings-row">
        {MEMORY_SEARCH_CHOICES.map(({ mode, label }) => (
          <Choice
            key={mode}
            label={label}
            on={memorySearch === mode}
            onClick={() => onChange({ ...settings, memory_search: mode })}
          />
        ))}
      </div>
      <p className="settings-hint">
        How the partner finds what it remembers about your words. Meaning also
        catches different wording, like "house" for "base", using a small local
        model that loads in the background. Both uses keywords and meaning.
      </p>
    </>
  );
}
