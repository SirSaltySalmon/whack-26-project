import type { Settings } from "../../lib/protocol.generated.ts";

export type ToggleName = "pause" | "mic" | "vision";

export interface AvatarToggle {
  name: ToggleName;
  /** Away from the default. Shown even when the character isn't hovered, so it's never a mystery. */
  pressed: boolean;
  label: string;
  title: string;
  /** The settings to send when it's clicked. Every other field is kept as it is. */
  next: Settings;
}

/** The pause, mic and vision buttons under the character, in order. Pure, so it's easy to test. */
export function avatarToggles(settings: Settings): AvatarToggle[] {
  const paused = settings.paused ?? false;
  const micOn = settings.mic_enabled ?? true;
  const visionOn = settings.vision_enabled ?? true;
  return [
    {
      name: "pause",
      pressed: paused,
      label: paused ? "Resume the partner" : "Pause the partner",
      title: paused
        ? "Paused. Click to let the partner talk again; it asks anything it wants to learn first."
        : "Pause: the partner stops talking but keeps listening, watching and taking notes",
      next: { ...settings, paused: !paused },
    },
    {
      name: "mic",
      pressed: !micOn,
      label: micOn ? "Mute your mic" : "Unmute your mic",
      title: micOn
        ? "Mute: the partner stops hearing you, and you type instead"
        : "Muted: the partner can't hear you. Click to talk again",
      next: { ...settings, mic_enabled: !micOn },
    },
    {
      name: "vision",
      pressed: !visionOn,
      label: visionOn ? "Blind the partner" : "Let the partner see again",
      title: visionOn
        ? "Blind: the partner stops watching the screen, but keeps listening and talking"
        : "Blinded: the partner can't see the game. Click to let it watch again",
      next: { ...settings, vision_enabled: !visionOn },
    },
  ];
}
