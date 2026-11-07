import { useEffect, useRef, useState } from "react";
import type {
  Brain,
  DebugRegion,
  MemoryToast,
  QuestionAsk,
  SettingsState,
} from "../../lib/protocol.generated.ts";
import { logger } from "../../lib/logger.ts";
import { applySubtitle, type SubtitleLine } from "../logic/subtitles.ts";

const SUBTITLE_LINGER_MS = 2500;
// Unanswered questions go away on their own: the partner can't keep covering the game.
const QUESTION_MS = 30000;
// The brain sends regions about twice a second while debugging, so silence means it stopped.
const DEBUG_REGIONS_STALE_MS = 3000;

export interface ShownToast {
  id: number;
  toast: MemoryToast;
}

export interface CompanionFeed {
  subtitle: SubtitleLine | null;
  toasts: ShownToast[];
  question: QuestionAsk | null;
  settings: SettingsState | null;
  debugRegions: DebugRegion[];
  handle(message: Brain): void;
  dismissToast(id: number): void;
  dismissQuestion(): void;
}

/** Holds what the brain says to the player, apart from the cards and pointer App manages. */
export function useCompanionFeed(): CompanionFeed {
  const [subtitle, setSubtitle] = useState<SubtitleLine | null>(null);
  const [toasts, setToasts] = useState<ShownToast[]>([]);
  const [question, setQuestion] = useState<QuestionAsk | null>(null);
  const [settings, setSettings] = useState<SettingsState | null>(null);
  const [debugRegions, setDebugRegions] = useState<DebugRegion[]>([]);
  const nextToastId = useRef(0);

  useEffect(() => {
    if (!subtitle?.done) return;
    const timer = setTimeout(() => setSubtitle(null), SUBTITLE_LINGER_MS);
    return () => clearTimeout(timer);
  }, [subtitle]);

  useEffect(() => {
    if (question === null) return;
    const timer = setTimeout(() => setQuestion(null), QUESTION_MS);
    return () => clearTimeout(timer);
  }, [question]);

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
        setQuestion(message);
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
    question,
    settings,
    debugRegions,
    handle,
    dismissToast: (id) =>
      setToasts((current) => current.filter((shown) => shown.id !== id)),
    dismissQuestion: () => setQuestion(null),
  };
}
