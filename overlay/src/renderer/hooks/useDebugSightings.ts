import { useCallback, useEffect, useRef, useState } from "react";
import type { DebugSighting } from "../../lib/protocol.generated.ts";
import {
  addSightings,
  liveSightings,
  nextExpiry,
  type ShownSighting,
} from "../logic/debugSightings.ts";

export interface DebugSightingsFeed {
  shown: ShownSighting[];
  add(incoming: DebugSighting[]): void;
}

/** Holds the debug view's sightings and drops each once its ttl runs out. */
export function useDebugSightings(): DebugSightingsFeed {
  const [shown, setShown] = useState<ShownSighting[]>([]);
  const nextId = useRef(0);

  // One timer, for whichever runs out first. The CSS fade has already hidden it by then.
  useEffect(() => {
    const expiry = nextExpiry(shown);
    if (expiry === null) return;
    const timer = setTimeout(
      () => setShown((current) => liveSightings(current, Date.now())),
      Math.max(0, expiry - Date.now()),
    );
    return () => clearTimeout(timer);
  }, [shown]);

  const add = useCallback((incoming: DebugSighting[]) => {
    // Ids are taken here, outside the updater, which React may run twice.
    const firstId = nextId.current;
    nextId.current += incoming.length;
    const now = Date.now();
    setShown((current) => addSightings(current, incoming, now, firstId));
  }, []);

  return { shown, add };
}
