import { useEffect, useRef, useState } from "react";
import type {
  Brain,
  MemoryToast,
  QuestionAsk,
  SettingsState,
} from "../../lib/protocol.generated.ts";
import { logger } from "../../lib/logger.ts";
import { applySubtitle, type SubtitleLine } from "../logic/subtitles.ts";

const SUBTITLE_LINGER_MS = 2500;
// Unanswered questions go away on their own: the partner can't keep covering the game.
const QUESTION_MS = 30000;

export interface ShownToast {
  id: number;
  toast: MemoryToast;
}

export interface CompanionFeed {
  subtitle: SubtitleLine | null;
  toasts: ShownToast[];
  question: QuestionAsk | null;
  settings: SettingsState | null;
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
      default:
        logger.warn(`No handler for ${message.type}`);
    }
  };

  return {
    subtitle,
    toasts,
    question,
    settings,
    handle,
    dismissToast: (id) =>
      setToasts((current) => current.filter((shown) => shown.id !== id)),
    dismissQuestion: () => setQuestion(null),
  };
}
