import { useState } from "react";
import { Field } from "../../components/ui.tsx";
import type { ChangeMemory } from "./useMemoryChanges.ts";

export function MemoryCreateControls({
  game,
  disabled,
  onChange,
}: {
  game: string;
  disabled: boolean;
  onChange: ChangeMemory;
}) {
  const [mode, setMode] = useState<"add" | "clear" | null>(null);
  const [subject, setSubject] = useState("player");
  const [attribute, setAttribute] = useState("");
  const [value, setValue] = useState("");
  const [confirmation, setConfirmation] = useState("");
  return (
    <fieldset className="mem-admin-fields" disabled={disabled}>
      <div className="mem-create-buttons">
        <button
          className="cc-button"
          type="button"
          onClick={() => setMode(mode === "add" ? null : "add")}
        >
          Add fact
        </button>
        <button
          className="cc-button"
          type="button"
          onClick={() => void onChange({ operation: "seed" })}
        >
          Add sample data
        </button>
        <button
          className="cc-button"
          type="button"
          onClick={() => setMode(mode === "clear" ? null : "clear")}
        >
          Clear all memory
        </button>
      </div>
      {mode === "add" && (
        <form
          className="cc-grid mem-inline-editor"
          onSubmit={async (event) => {
            event.preventDefault();
            if (
              await onChange({
                operation: "remember",
                game: game || null,
                subject,
                attribute,
                value,
              })
            ) {
              setMode(null);
              setValue("");
            }
          }}
        >
          <p className="cc-hint">
            Add a player-confirmed fact for {game || "all games"}.
          </p>
          <Field label="Subject">
            <input
              className="cc-input"
              value={subject}
              required
              maxLength={200}
              onChange={(e) => setSubject(e.target.value)}
            />
          </Field>
          <Field label="Attribute">
            <input
              className="cc-input"
              value={attribute}
              required
              maxLength={200}
              onChange={(e) => setAttribute(e.target.value)}
            />
          </Field>
          <Field label="Value">
            <input
              className="cc-input"
              value={value}
              required
              maxLength={2000}
              onChange={(e) => setValue(e.target.value)}
            />
          </Field>
          <button className="cc-button" type="submit">
            Save fact
          </button>
          <button
            className="cc-button"
            type="button"
            onClick={() => setMode(null)}
          >
            Cancel
          </button>
        </form>
      )}
      {mode === "clear" && (
        <div className="mem-inline-editor">
          <p>
            Erases all games' facts, history, notes, questions and
            conversation/event records. Keeps learned profiles and settings. A
            database backup is saved first.
          </p>
          <Field label="Type CLEAR to confirm">
            <input
              className="cc-input"
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
            />
          </Field>
          <button
            className="cc-button"
            type="button"
            disabled={confirmation !== "CLEAR"}
            onClick={async () => {
              if (await onChange({ operation: "clear", confirmation })) {
                setMode(null);
                setConfirmation("");
              }
            }}
          >
            Clear all memory
          </button>{" "}
          <button
            className="cc-button"
            type="button"
            onClick={() => setMode(null)}
          >
            Cancel
          </button>
        </div>
      )}
    </fieldset>
  );
}
