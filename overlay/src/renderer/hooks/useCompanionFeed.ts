import { useEffect, useRef, useState } from "react";
import type {
  Brain,
  DebugRegion,
  MemoryToast,
  SettingsState,
} from "../../lib/protocol.generated.ts";
import { logger } from "../../lib/logger.ts";
import { applySubtitle, type SubtitleLine } from "../logic/subtitles.ts";

const SUBTITLE_LINGER_MS = 2500;
// The brain sends regions about twice a second while debugging, so silence means it stopped.
const DEBUG_REGIONS_STALE_MS = 3000;

export interface ShownToast {
  id: number;
  toast: MemoryToast;
}

export interface CompanionFeed {
  subtitle: SubtitleLine | null;
  toasts: ShownToast[];
  settings: SettingsState | null;
  debugRegions: DebugRegion[];
  handle(message: Brain): void;
  dismissToast(id: number): void;
}

/** Holds what the brain says to the player, apart from the cards and pointer App manages. */
export function useCompanionFeed(): CompanionFeed {
  const [subtitle, setSubtitle] = useState<SubtitleLine | null>(null);
  const [toasts, setToasts] = useState<ShownToast[]>([]);
  const [settings, setSettings] = useState<SettingsState | null>(null);
  const [debugRegions, setDebugRegions] = useState<DebugRegion[]>([]);
  const nextToastId = useRef(0);

  useEffect(() => {
    if (!subtitle?.done) return;
    const timer = setTimeout(() => setSubtitle(null), SUBTITLE_LINGER_MS);
    return () => clearTimeout(timer);
  }, [subtitle]);

  // Each message is a new array, so this restarts the countdown on every message.
  useEffect(() => {
    if (debugRegions.length === 0) return;
    const timer = setTimeout(() => setDebugRegions([]), DEBUG_REGIONS_STALE_MS);
    return () => clearTimeout(timer);
  }, [debugRegions]);

  const handle = (message: Brain): void => {
    switch (message.type) {
      case "subtitle.chunk":
        setSubtitle((current) => applySubtitle(current, message));
        break;
      case "toast.memory": {
        const id = nextToastId.current++;
        setToasts((current) => [...current, { id, toast: message }]);
        break;
      }
      case "question.ask":
        // Questions are spoken and subtitled now, and answered like any turn. Only an older brain
        // sends this, and a popup would cover the game.
        logger.debug(`Ignored question.ask: ${message.text}`);
        break;
      case "settings.state":
        setSettings(message);
        break;
      case "debug.regions":
        setDebugRegions(message.regions);
        break;
      default:
        logger.warn(`No handler for ${message.type}`);
    }
  };

  return {
    subtitle,
    toasts,
    settings,
    debugRegions,
    handle,
    dismissToast: (id) =>
      setToasts((current) => current.filter((shown) => shown.id !== id)),
  };
}
