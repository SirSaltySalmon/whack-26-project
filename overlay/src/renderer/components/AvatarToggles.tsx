import type { ReactNode } from "react";
import type { Settings } from "../../lib/protocol.generated.ts";
import { CHAT_OFFLINE_HINT } from "../logic/chat.ts";
import { avatarToggles, type ToggleName } from "../logic/toggles.ts";

const SLASH = <path d="M3 3l18 18" />;

/** Drawn rather than emoji, so they match at every size and take the button's colour. */
function Icon({ name, pressed }: { name: ToggleName; pressed: boolean }) {
  let shape: ReactNode;
  switch (name) {
    case "pause":
      // Paused shows play: the icon is what a click does.
      shape = pressed ? (
        <path d="M8 5v14l11-7z" fill="currentColor" />
      ) : (
        <path d="M9 5v14M15 5v14" />
      );
      break;
    case "mic":
      shape = (
        <>
          <rect x="9" y="3" width="6" height="11" rx="3" />
          <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
          {pressed && SLASH}
        </>
      );
      break;
    case "vision":
      shape = (
        <>
          <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
          <circle cx="12" cy="12" r="3" />
          {pressed && SLASH}
        </>
      );
      break;
  }
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {shape}
    </svg>
  );
}

interface AvatarTogglesProps {
  /** Null while the brain is away: the buttons stay, disabled, to say why. */
  settings: Settings | null;
  onChange(settings: Settings): void;
}

/** Pause, mute and blind, under the character. A pressed one stays visible without hovering. */
export function AvatarToggles({ settings, onChange }: AvatarTogglesProps) {
  return (
    <div className="avatar-toggles">
      {avatarToggles(settings ?? {}).map((toggle) => (
        <button
          key={toggle.name}
          className="avatar-toggle"
          data-interactive
          type="button"
          aria-label={toggle.label}
          aria-pressed={settings !== null && toggle.pressed}
          title={settings ? toggle.title : CHAT_OFFLINE_HINT}
          disabled={settings === null}
          onClick={() => onChange(toggle.next)}
        >
          <Icon
            name={toggle.name}
            pressed={settings !== null && toggle.pressed}
          />
        </button>
      ))}
    </div>
  );
}
