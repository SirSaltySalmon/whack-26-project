import { useCallback, useEffect, useState } from "react";
import {
  addLines,
  EMPTY_LATENCY,
  newLines,
  type LatencyState,
} from "../../logic/latency.ts";

// Module scope, because only the open tab is mounted and the log keeps just its last 2000 lines:
// numbers kept here survive switching tabs and outlast the lines they came from.
let seen: readonly string[] = [];
let kept: LatencyState = EMPTY_LATENCY;

/** Latency since the brain last started, read from the log the Console tab shows. */
export function useLatency(logs: readonly string[]): {
  state: LatencyState;
  clear(): void;
} {
  const [state, setState] = useState(kept);

  useEffect(() => {
    const added = newLines(seen, logs);
    seen = logs;
    if (added.length === 0) return;
    kept = addLines(kept, added);
    setState(kept);
  }, [logs]);

  const clear = useCallback(() => {
    kept = EMPTY_LATENCY;
    setState(kept);
  }, []);

  return { state, clear };
}
