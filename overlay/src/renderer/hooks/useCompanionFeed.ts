import { useEffect, useRef, useState } from "react";
import type {
  Brain,
  DebugBrain,
  DebugRegion,
  MemoryToast,
  SettingsState,
} from "../../lib/protocol.generated.ts";
import { logger } from "../../lib/logger.ts";
import {
  applySubtitle,
  endStaleSubtitle,
  type SubtitleLine,
} from "../logic/subtitles.ts";
import type { ShownSighting } from "../logic/debugSightings.ts";
import { useDebugSightings } from "./useDebugSightings.ts";

const SUBTITLE_LINGER_MS = 2500;
// Spoken words arrive well under a second apart, so this long without one means the line is over.
const SUBTITLE_STALE_MS = 8000;
// The brain sends regions about twice a second while debugging, so silence means it stopped.
const DEBUG_REGIONS_STALE_MS = 3000;

export interface ShownToast {
  id: number;
  toast: MemoryToast;
}

/** `seq` changes with every message, so the same level sent again shows the alert again. */
export interface DangerSignal {
  level: "none" | "medium" | "high";
  seq: number;
}

export interface CompanionFeed {
  subtitle: SubtitleLine | null;
  danger: DangerSignal | null;
  toasts: ShownToast[];
  settings: SettingsState | null;
  debugRegions: DebugRegion[];
  debugSightings: ShownSighting[];
  debugBrain: DebugBrain | null;
  handle(message: Brain): void;
  dismissToast(id: number): void;
}

/** Holds what the brain says to the player, apart from the cards and pointer App manages. */
export function useCompanionFeed(): CompanionFeed {
  const [subtitle, setSubtitle] = useState<SubtitleLine | null>(null);
  const [toasts, setToasts] = useState<ShownToast[]>([]);
  const [settings, setSettings] = useState<SettingsState | null>(null);
  const [debugRegions, setDebugRegions] = useState<DebugRegion[]>([]);
  const [debugBrain, setDebugBrain] = useState<DebugBrain | null>(null);
  const [danger, setDanger] = useState<DangerSignal | null>(null);
  const sightings = useDebugSightings();
  const nextToastId = useRef(0);

  useEffect(() => {
    if (subtitle === null) return;
    if (subtitle.done) {
      const timer = setTimeout(() => setSubtitle(null), SUBTITLE_LINGER_MS);
      return () => clearTimeout(timer);
    }
    // Each chunk is a new object, so this restarts while words keep coming. A line whose speech
    // failed never gets its final chunk, and would otherwise stay on screen for good.
    const id = subtitle.utteranceId;
    const timer = setTimeout(() => {
      logger.warn(
        `Subtitle ${id} got no words for ${SUBTITLE_STALE_MS} ms and never ended; fading it`,
      );
      setSubtitle((current) => endStaleSubtitle(current, id));
    }, SUBTITLE_STALE_MS);
    return () => clearTimeout(timer);
  }, [subtitle]);

  // Each message is a new array, so this restarts the countdown on every message.
  useEffect(() => {
    if (debugRegions.length === 0) return;
    const timer = setTimeout(() => setDebugRegions([]), DEBUG_REGIONS_STALE_MS);
    return () => clearTimeout(timer);
  }, [debugRegions]);

  // Snapshots come about twice a second while debugging, so silence means the brain stopped.
  useEffect(() => {
    if (debugBrain === null) return;
    const timer = setTimeout(() => setDebugBrain(null), DEBUG_REGIONS_STALE_MS);
    return () => clearTimeout(timer);
  }, [debugBrain]);

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
      case "debug.sightings":
        sightings.add(message.sightings);
        break;
      case "debug.brain":
        setDebugBrain(message);
        break;
      case "danger.state":
        setDanger((current) => ({
          level: message.level,
          seq: (current?.seq ?? 0) + 1,
        }));
        break;
      default:
        logger.warn(`No handler for ${message.type}`);
    }
  };

  return {
    subtitle,
    danger,
    toasts,
    settings,
    debugRegions,
    debugSightings: sightings.shown,
    debugBrain,
    handle,
    dismissToast: (id) =>
      setToasts((current) => current.filter((shown) => shown.id !== id)),
  };
}
