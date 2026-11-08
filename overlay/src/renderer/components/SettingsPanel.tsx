import type { Settings, SettingsState } from "../../lib/protocol.generated.ts";
import type { Avatars } from "../hooks/useAvatars.ts";
import type { Skin } from "../hooks/useSkin.ts";
import type { Frame } from "../logic/layout.ts";
import { TEXT_CARD_LIMITS } from "../logic/layout.ts";
import { SettingsFields } from "../shared/SettingsFields.tsx";
import { SkinPicker } from "../shared/SkinPicker.tsx";
import { AvatarSettings } from "./AvatarSettings.tsx";
import { CardWindow } from "./CardWindow.tsx";

interface SettingsPanelProps {
  state: SettingsState | null;
  avatars: Avatars;
  skin: Skin;
  frame: Frame;
  onFrame(frame: Frame): void;
  onChange(settings: Settings): void;
  /** Brings back the last wiki page after its window was closed. Null when there's none to reopen. */
  onReopenWiki: (() => void) | null;
  onClose(): void;
}

export function SettingsPanel({
  state,
  avatars,
  skin,
  frame,
  onFrame,
  onChange,
  onReopenWiki,
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
        {/* Overlay only, so it works before the brain connects. */}
        {onReopenWiki && (
          <>
            <h3 className="settings-heading">Wiki</h3>
            <div className="settings-row">
              <button
                className="option option-plain"
                type="button"
                onClick={onReopenWiki}
              >
                Reopen the last page
              </button>
            </div>
          </>
        )}
        {/* Visual only, so these work before the brain connects. */}
        <h3 className="settings-heading">Look</h3>
        <SkinPicker skin={skin} />
        <AvatarSettings avatars={avatars} />
      </div>
    </CardWindow>
  );
}
