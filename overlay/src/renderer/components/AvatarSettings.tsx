import type { Avatars } from "../hooks/useAvatars.ts";
import { AvatarGallery } from "../shared/AvatarGallery.tsx";

/** Pick or upload here. Renaming, mirroring and deleting are in the Control Center's Avatar tab. */
export function AvatarSettings({ avatars }: { avatars: Avatars }) {
  return (
    <>
      <h3 className="settings-heading">Avatar</h3>
      <AvatarGallery avatars={avatars} />
      <div className="settings-row">
        <button
          className={`option${avatars.removeBackground ? " option-on" : ""}`}
          type="button"
          aria-pressed={avatars.removeBackground}
          onClick={() => avatars.setRemoveBackground(!avatars.removeBackground)}
        >
          Remove white background
        </button>
      </div>
      <p className="settings-hint">
        {avatars.error ??
          "Applies to new uploads. Rename, mirror or delete them in the Control Center. They stay on this computer."}
      </p>
    </>
  );
}
