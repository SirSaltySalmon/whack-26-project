import { useState } from "react";

/** Chips for STT_KEYTERMS. Enter or comma adds one. */
export function Keyterms({
  terms,
  onChange,
}: {
  terms: string[];
  onChange(terms: string[]): void;
}) {
  const [draft, setDraft] = useState("");

  const add = (): void => {
    const term = draft.trim();
    if (term && !terms.includes(term)) onChange([...terms, term]);
    setDraft("");
  };

  return (
    <div className="chips">
      {terms.map((term) => (
        <span key={term} className="chip">
          {term}
          <button
            type="button"
            aria-label={`Remove ${term}`}
            onClick={() => onChange(terms.filter((t) => t !== term))}
          >
            ×
          </button>
        </span>
      ))}
      <input
        className="chip-input"
        value={draft}
        placeholder={terms.length ? "Add another" : "Eye of Cthulhu"}
        spellCheck={false}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === ",") {
            event.preventDefault();
            add();
          } else if (event.key === "Backspace" && !draft && terms.length) {
            onChange(terms.slice(0, -1));
          }
        }}
        onBlur={add}
      />
    </div>
  );
}
