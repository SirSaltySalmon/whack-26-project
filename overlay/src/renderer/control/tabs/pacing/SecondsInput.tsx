import { useEffect, useState } from "react";
import { clampPacing, type PacingKey } from "../../../../lib/pacing.ts";

/**
 * Commits on Enter or leaving the box rather than on every keystroke, so typing "45" doesn't
 * send the brain 4 seconds on the way there.
 */
export function SecondsInput({
  name,
  value,
  max,
  onCommit,
}: {
  name: PacingKey;
  value: number;
  max: number;
  onCommit(value: number): void;
}) {
  const [draft, setDraft] = useState(String(value));
  const [editing, setEditing] = useState(false);

  // A preset or the brain's echo replaces the text, but never while it's being typed in.
  useEffect(() => {
    if (!editing) setDraft(String(value));
  }, [value, editing]);

  const commit = () => {
    setEditing(false);
    const parsed = Number(draft);
    if (draft.trim() === "" || !Number.isFinite(parsed)) {
      setDraft(String(value));
      return;
    }
    const next = clampPacing(name, parsed);
    setDraft(String(next));
    if (next !== value) onCommit(next);
  };

  return (
    <input
      className="cc-input"
      type="number"
      inputMode="decimal"
      min={0}
      max={max}
      step={1}
      value={draft}
      onFocus={() => setEditing(true)}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") event.currentTarget.blur();
        if (event.key === "Escape") {
          setDraft(String(value));
          setEditing(false);
          event.currentTarget.blur();
        }
      }}
    />
  );
}
