import { useEffect, useState } from "react";
import type { Avatars } from "../../../hooks/useAvatars.ts";
import {
  MAX_NAME_LENGTH,
  type UploadedAvatar,
} from "../../../logic/avatars.ts";
import { Toggle } from "../../components/ui.tsx";

/** Edits an upload. Every change is re-cut from the original, so any of them can be undone. */
export function AvatarEditor({
  avatar,
  avatars,
}: {
  avatar: UploadedAvatar;
  avatars: Avatars;
}) {
  const [name, setName] = useState(avatar.name);
  const [confirming, setConfirming] = useState(false);

  // Follows the saved name, which comes back tidied, with extra spaces gone.
  useEffect(() => setName(avatar.name), [avatar.name]);

  const saveName = (): void => {
    if (name.trim() === "") setName(avatar.name);
    else if (name !== avatar.name) avatars.edit(avatar.id, { name });
  };

  return (
    <div className="avatar-editor">
      <div className="avatar-editor-preview">
        <img
          src={avatar.image}
          alt={`${avatar.name}, as the overlay shows it`}
        />
      </div>
      <div className="avatar-editor-fields">
        <label className="cc-field">
          <span className="cc-field-label">Name</span>
          <input
            className="cc-input"
            value={name}
            maxLength={MAX_NAME_LENGTH}
            spellCheck={false}
            autoComplete="off"
            onChange={(event) => setName(event.target.value)}
            onBlur={saveName}
            onKeyDown={(event) => {
              if (event.key === "Enter") event.currentTarget.blur();
              if (event.key === "Escape") setName(avatar.name);
            }}
          />
        </label>
        <div className="cc-toggles">
          <Toggle
            label="Remove white background"
            hint="Clears plain light background reachable from the edges, so the game shows around the character."
            on={avatar.removeBackground}
            onChange={(removeBackground) =>
              avatars.edit(avatar.id, { removeBackground })
            }
          />
          <Toggle
            label="Mirror"
            hint="Flips it left to right, so it can face the game."
            on={avatar.mirrored}
            onChange={(mirrored) => avatars.edit(avatar.id, { mirrored })}
          />
        </div>
        <div className="avatar-editor-actions">
          {confirming ? (
            <>
              <span className="cc-hint">
                Delete {avatar.name}? This can't be undone.
              </span>
              <button
                className="cc-button cc-button-stop"
                type="button"
                onClick={() => {
                  setConfirming(false);
                  avatars.remove(avatar.id);
                }}
              >
                Delete
              </button>
              <button
                className="cc-button cc-button-quiet"
                type="button"
                onClick={() => setConfirming(false)}
              >
                Keep it
              </button>
            </>
          ) : (
            <button
              className="cc-button"
              type="button"
              disabled={avatars.busy}
              onClick={() => setConfirming(true)}
            >
              Delete…
            </button>
          )}
          {avatars.busy && <span className="cc-hint">Updating…</span>}
        </div>
      </div>
    </div>
  );
}
