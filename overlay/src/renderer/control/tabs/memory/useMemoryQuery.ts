import { useCallback, useEffect, useRef, useState } from "react";
import type {
  MemoryContext,
  MemoryResults,
  MemoryToast,
} from "../../../../lib/protocol.generated.ts";
import { useControl } from "../../ControlContext.tsx";

const DEBOUNCE_MS = 250;

export interface MemoryQueryState {
  results: MemoryResults | null;
  recall: MemoryContext | null;
  error: string | null;
  /** The last "memory updated" toast, so the tab can show what just changed. */
  lastToast: MemoryToast | null;
  refresh(): void;
}

/**
 * Searches as the player types, and again whenever the partner remembers something. `game` null
 * reads the game being played, or the one played last when the partner is off.
 */
export function useMemoryQuery(
  text: string,
  includeHistory: boolean,
  game: string | null,
): MemoryQueryState {
  const { request, onPush, connected } = useControl();
  const [results, setResults] = useState<MemoryResults | null>(null);
  const [recall, setRecall] = useState<MemoryContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastToast, setLastToast] = useState<MemoryToast | null>(null);
  // Replies can arrive out of order while typing; only the newest query may show.
  const latest = useRef(0);

  const run = useCallback(() => {
    latest.current += 1;
    const ticket = latest.current;
    const fresh = (): boolean => ticket === latest.current;
    Promise.all([
      request(
        {
          type: "memory.query",
          text,
          include_history: includeHistory,
          limit: 100,
          game,
        },
        "memory.results",
      ),
      request({ type: "memory.context_preview", text, game }, "memory.context"),
    ])
      .then(([found, context]) => {
        if (!fresh()) return;
        setResults(found);
        setRecall(context);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (fresh())
          setError(reason instanceof Error ? reason.message : String(reason));
      });
  }, [request, text, includeHistory, game]);

  // Again when the partner starts or stops: the recall preview only has live state while it runs.
  useEffect(() => {
    const timer = setTimeout(run, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [run, connected]);

  useEffect(
    () =>
      onPush((message) => {
        if (message.type !== "toast.memory") return;
        setLastToast(message);
        run();
      }),
    [onPush, run],
  );

  return { results, recall, error, lastToast, refresh: run };
}
