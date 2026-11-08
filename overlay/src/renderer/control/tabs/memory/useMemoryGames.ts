import { useCallback, useEffect, useRef, useState } from "react";
import type { MemoryGames } from "../../../../lib/protocol.generated.ts";
import { useControl } from "../../ControlContext.tsx";

export interface MemoryGamesState {
  /** Null until the first answer. */
  list: MemoryGames | null;
  error: string | null;
  refresh(): void;
}

/** Which games memory holds, asked again when the partner starts or stops and on new memories. */
export function useMemoryGames(revision = 0): MemoryGamesState {
  const { request, onPush, connected } = useControl();
  const [list, setList] = useState<MemoryGames | null>(null);
  const [error, setError] = useState<string | null>(null);
  const latest = useRef(0);

  const refresh = useCallback(() => {
    latest.current += 1;
    const ticket = latest.current;
    request({ type: "memory.list_games" }, "memory.games").then(
      (reply) => {
        if (ticket !== latest.current) return;
        setList(reply);
        setError(null);
      },
      (reason: unknown) => {
        if (ticket === latest.current)
          setError(reason instanceof Error ? reason.message : String(reason));
      },
    );
  }, [request]);

  // `connected` decides who answers, and a running partner names the current game.
  useEffect(() => {
    refresh();
  }, [refresh, connected, revision]);

  useEffect(
    () =>
      onPush((message) => {
        if (message.type === "toast.memory") refresh();
      }),
    [onPush, refresh],
  );

  return { list, error, refresh };
}
