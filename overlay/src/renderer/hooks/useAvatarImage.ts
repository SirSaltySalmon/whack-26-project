import { useState } from "react";
import { logger } from "../../lib/logger.ts";
import defaultAvatarUrl from "../assets/avatar-default.png";
import { prepareAvatarImage } from "../lib/avatarImage.ts";
import { savedAvatarImage, savedRemoveBackground } from "../lib/storage.ts";

export interface AvatarImage {
  src: string;
  custom: boolean;
  removeBackground: boolean;
  busy: boolean;
  error: string | null;
  choose(file: File): void;
  reset(): void;
  setRemoveBackground(remove: boolean): void;
}

/**
 * The avatar's picture: the bundled default, or one the player picked. A custom picture is kept
 * in local storage, so it stays until they reset it, and it never leaves this machine.
 */
export function useAvatarImage(): AvatarImage {
  const [custom, setCustom] = useState(savedAvatarImage.load);
  const [removeBackground, setRemove] = useState(savedRemoveBackground.load);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return {
    src: custom ?? defaultAvatarUrl,
    custom: custom !== null,
    removeBackground,
    busy,
    error,
    choose(file) {
      setBusy(true);
      setError(null);
      prepareAvatarImage(file, removeBackground)
        .then((dataUrl) => {
          setCustom(dataUrl);
          // Still shown this run if it can't be saved; it just won't come back next time.
          if (!savedAvatarImage.save(dataUrl)) {
            setError("Couldn't save it, so it will reset next time.");
          }
        })
        .catch((reason: unknown) => {
          logger.warn("Could not use the picked avatar image", reason);
          setError(
            reason instanceof Error
              ? reason.message
              : "That image didn't work.",
          );
        })
        .finally(() => setBusy(false));
    },
    reset() {
      savedAvatarImage.clear();
      setCustom(null);
      setError(null);
    },
    setRemoveBackground(remove) {
      savedRemoveBackground.save(remove);
      setRemove(remove);
    },
  };
}
