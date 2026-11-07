import type { Settings, SettingsState } from "../../lib/protocol.generated.ts";
import type { Frame } from "../logic/layout.ts";
import { TEXT_CARD_LIMITS } from "../logic/layout.ts";
import { CardWindow } from "./CardWindow.tsx";

interface SettingsPanelProps {
  state: SettingsState | null;
  frame: Frame;
  onFrame(frame: Frame): void;
  onChange(settings: Settings): void;
  onClose(): void;
}

function Choice({
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

/** Buttons only, so changing a setting never takes the keyboard from the game. */
export function SettingsPanel({
  state,
  frame,
  onFrame,
  onChange,
  onClose,
}: SettingsPanelProps) {
  const body = (() => {
    if (state === null) {
      return <p className="settings-hint">Waiting for the brain to connect.</p>;
    }
    const { settings } = state;
    const proactive = settings.proactive ?? true;
    const voices = state.voices ?? [];
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
        <h3 className="settings-heading">Personality</h3>
        <div className="settings-row">
          {(state.personalities ?? []).map((name) => (
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
      </>
    );
  })();

  return (
    <CardWindow
      rectId="settings"
      title="Settings"
      frame={frame}
      limits={TEXT_CARD_LIMITS}
      zIndex={50}
      onFrame={onFrame}
      onRaise={() => undefined}
      onClose={onClose}
    >
      <div className="settings">{body}</div>
    </CardWindow>
  );
}
