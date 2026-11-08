import { useEffect, useState } from "react";
import { logger } from "../../lib/logger.ts";
import { savedSkin } from "../lib/storage.ts";
import { parseSkin, type SkinId } from "../logic/skins.ts";

const CHANNEL = "overlay-skin";

// One per window, since a BroadcastChannel never hears its own messages.
let channel: BroadcastChannel | null = null;

function shared(): BroadcastChannel | null {
  if (channel === null && typeof BroadcastChannel !== "undefined") {
    channel = new BroadcastChannel(CHANNEL);
  }
  return channel;
}

export interface Skin {
  skin: SkinId;
  choose(skin: SkinId): void;
}

/**
 * The overlay's look, shared by the overlay and the Control Center: either can change it and the
 * other follows. With `apply`, it also sets `data-skin` on this window's root element, which is
 * all a skin needs: the stylesheets in `skins/` do the rest.
 */
export function useSkin(apply = false): Skin {
  const [skin, setSkin] = useState(savedSkin.load);

  useEffect(() => {
    const current = shared();
    if (current === null) {
      logger.warn(
        "BroadcastChannel is missing, so skin changes won't sync between windows",
      );
      return;
    }
    const handler = (event: MessageEvent): void =>
      setSkin(parseSkin(event.data));
    current.addEventListener("message", handler);
    return () => current.removeEventListener("message", handler);
  }, []);

  useEffect(() => {
    if (apply) document.documentElement.dataset["skin"] = skin;
  }, [apply, skin]);

  return {
    skin,
    choose(next) {
      savedSkin.save(next);
      setSkin(next);
      try {
        shared()?.postMessage(next);
      } catch (error) {
        logger.warn("Could not tell the other window about the skin", error);
      }
    },
  };
}
