import { useAvatars } from "../../../hooks/useAvatars.ts";
import { AvatarGallery } from "../../../shared/AvatarGallery.tsx";
import { BUILT_IN_AVATARS } from "../../../logic/avatars.ts";
import { Notice, Section, Toggle } from "../../components/ui.tsx";
import { AvatarEditor } from "./AvatarEditor.tsx";
import "./avatar.css";

/**
 * Visual only, so it works without the partner running. The overlay shares the same saved
 * avatars and follows every change here as it happens.
 */
export function AvatarTab() {
  const avatars = useAvatars();
  const chosen =
    avatars.uploads?.find((avatar) => avatar.id === avatars.choice) ?? null;
  const builtIn = BUILT_IN_AVATARS.find(
    (avatar) => avatar.id === avatars.choice,
  );

  return (
    <div className="cc-page">
      <Section
        title="Avatar"
        hint="How the partner looks in the overlay. Picking one shows it there right away."
      >
        <AvatarGallery avatars={avatars} large />
        <div className="cc-toggles">
          <Toggle
            label="Remove white background from uploads"
            hint="Applies to the next image you upload. Turn it off for art whose light background you want to keep."
            on={avatars.removeBackground}
            onChange={avatars.setRemoveBackground}
          />
        </div>
        {avatars.error && <Notice tone="warn">{avatars.error}</Notice>}
        <p className="cc-hint">
          Uploads are scaled to 512 px and stay on this computer.
        </p>
      </Section>

      <Section title={chosen ? `Edit ${chosen.name}` : "Edit"}>
        {chosen ? (
          <AvatarEditor key={chosen.id} avatar={chosen} avatars={avatars} />
        ) : (
          <p className="cc-hint">
            {avatars.uploads === null
              ? "Loading your avatars…"
              : `${builtIn?.name ?? "This avatar"} is built in, so it can't be changed. Upload an image to get one you can rename, mirror and cut out.`}
          </p>
        )}
      </Section>
    </div>
  );
}
