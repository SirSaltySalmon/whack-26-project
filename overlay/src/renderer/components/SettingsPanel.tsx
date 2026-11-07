import type { Settings, SettingsState } from "../../lib/protocol.generated.ts";
import type { Frame } from "../logic/layout.ts";
import { TEXT_CARD_LIMITS } from "../logic/layout.ts";
import { SettingsFields } from "../shared/SettingsFields.tsx";
import { CardWindow } from "./CardWindow.tsx";

interface SettingsPanelProps {
  state: SettingsState | null;
  frame: Frame;
  onFrame(frame: Frame): void;
  onChange(settings: Settings): void;
  onClose(): void;
}

export function SettingsPanel({
  state,
  frame,
  onFrame,
  onChange,
  onClose,
}: SettingsPanelProps) {
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
      <div className="settings">
        {state === null ? (
          <p className="settings-hint">Waiting for the brain to connect.</p>
        ) : (
          <SettingsFields
            choices={{
              settings: state.settings,
              personalities: state.personalities ?? [],
              voices: state.voices ?? [],
            }}
            onChange={onChange}
          />
        )}
      </div>
    </CardWindow>
  );
}
