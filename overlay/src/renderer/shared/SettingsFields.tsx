import type { Settings, VoiceOption } from "../../lib/protocol.generated.ts";

export interface SettingsChoices {
  settings: Settings;
  personalities: string[];
  voices: VoiceOption[];
}

interface SettingsFieldsProps {
  choices: SettingsChoices;
  onChange(settings: Settings): void;
  /** The Control Center offers "default", which leaves the voice to ELEVENLABS_VOICE_ID. */
  allowDefaultVoice?: boolean;
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
export function SettingsFields({
  choices,
  onChange,
  allowDefaultVoice = false,
}: SettingsFieldsProps) {
  const { settings, personalities, voices } = choices;
  const proactive = settings.proactive ?? true;
  const micEnabled = settings.mic_enabled ?? true;
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
      {(voices.length > 0 || allowDefaultVoice) && (
        <>
          <h3 className="settings-heading">Voice</h3>
          <div className="settings-row">
            {allowDefaultVoice && (
              <Choice
                label="Default"
                on={!settings.voice_id}
                onClick={() => onChange({ ...settings, voice_id: null })}
              />
            )}
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
    </>
  );
}
