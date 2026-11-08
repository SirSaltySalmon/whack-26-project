import type { Settings, SettingsState } from "../../lib/protocol.generated.ts";
import type { Avatars } from "../hooks/useAvatars.ts";
import type { Frame } from "../logic/layout.ts";
import { TEXT_CARD_LIMITS } from "../logic/layout.ts";
import { SettingsFields } from "../shared/SettingsFields.tsx";
import { AvatarSettings } from "./AvatarSettings.tsx";
import { CardWindow } from "./CardWindow.tsx";

interface SettingsPanelProps {
  state: SettingsState | null;
  avatars: Avatars;
  frame: Frame;
  onFrame(frame: Frame): void;
  onChange(settings: Settings): void;
  onClose(): void;
}

export function SettingsPanel({
  state,
  avatars,
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
        {/* Visual only, so it works before the brain connects. */}
        <AvatarSettings avatars={avatars} />
      </div>
    </CardWindow>
  );
}
