import { useCallback, useRef, useState } from "react";
import type { MemoryAdminRequest } from "../../../../lib/protocol.generated.ts";
import { useControl } from "../../ControlContext.tsx";
import { MemoryActions } from "../../logic/memoryActions.ts";

export type ChangeMemory = (request: MemoryAdminRequest) => Promise<boolean>;

export function useMemoryChanges(onUpdated: () => void) {
  const { manageMemory, connected, process } = useControl();
  const actions = useRef(new MemoryActions());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const allowed = !connected && ["stopped", "crashed"].includes(process.state);
  const run = useCallback<ChangeMemory>(
    async (request) => {
      if (actions.current.busy || !allowed) return false;
      setBusy(true);
      setError("");
      setMessage("");
      try {
        const result = await actions.current.run(request, manageMemory);
        if (!result) return false;
        onUpdated();
        setMessage(
          result.backup
            ? `Memory cleared. Backup: ${result.backup}`
            : request.operation === "seed"
              ? "Sample notes and facts are under Memory test (sample)."
              : request.operation === "delete_note"
                ? "Session note deleted from memory and search."
                : request.operation === "edit_note"
                  ? "Session note saved. Search and recall updated."
                  : request.operation === "forget"
                    ? "Fact forgotten. Kept in History only."
                    : "Fact saved.",
        );
        return true;
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [allowed, manageMemory, onUpdated],
  );
  return { allowed, busy, error, message, run };
}
