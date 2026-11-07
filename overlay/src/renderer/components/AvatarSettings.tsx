import { useRef } from "react";
import type { AvatarImage } from "../hooks/useAvatarImage.ts";

/**
 * Picking a picture opens the system file dialog, which takes the keyboard until it closes. That's
 * the player's choice, unlike the other settings, which are buttons so the game keeps focus.
 */
export function AvatarSettings({ avatar }: { avatar: AvatarImage }) {
  const picker = useRef<HTMLInputElement>(null);

  return (
    <>
      <h3 className="settings-heading">Avatar</h3>
      <div className="settings-row">
        <button
          className="option"
          type="button"
          disabled={avatar.busy}
          onClick={() => picker.current?.click()}
        >
          {avatar.busy ? "Preparing…" : "Choose image…"}
        </button>
        <button
          className={`option${avatar.custom ? "" : " option-on"}`}
          type="button"
          aria-pressed={!avatar.custom}
          disabled={!avatar.custom || avatar.busy}
          onClick={avatar.reset}
        >
          Use default
        </button>
      </div>
      <div className="settings-row">
        <button
          className={`option${avatar.removeBackground ? " option-on" : ""}`}
          type="button"
          aria-pressed={avatar.removeBackground}
          onClick={() => avatar.setRemoveBackground(!avatar.removeBackground)}
        >
          Remove white background
        </button>
      </div>
      <p className="settings-hint">
        {avatar.error ??
          "Applies to the next image you choose. It stays on this computer."}
      </p>
      <input
        ref={picker}
        className="avatar-picker"
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif,image/bmp"
        onChange={(event) => {
          const file = event.currentTarget.files?.[0];
          // Cleared so picking the same file again still counts as a change.
          event.currentTarget.value = "";
          if (file) avatar.choose(file);
        }}
      />
    </>
  );
}
