import { useEffect, useState } from "react";
import { Notice, Section } from "../../components/ui.tsx";
import { useControl } from "../../ControlContext.tsx";

export function InstructionsEditor() {
  const { config, choices, changeSettings, connected } = useControl();
  const saved = config.settings.custom_instructions;
  const [draft, setDraft] = useState(saved);
  const [done, setDone] = useState(false);
  useEffect(() => {
    setDraft(saved);
  }, [saved]);
  return (
    <Section
      title="Custom instructions"
      hint="Tell your partner how to help, e.g. avoid spoilers or focus on building. Saved separately from facts. Truth and trust rules still apply."
    >
      <textarea
        className="cc-input"
        aria-label="Custom instructions"
        rows={4}
        maxLength={4000}
        value={draft}
        onChange={(event) => {
          setDraft(event.target.value);
          setDone(false);
        }}
      />
      <button
        className="cc-button"
        type="button"
        onClick={() => {
          changeSettings({ ...choices.settings, custom_instructions: draft });
          setDone(true);
        }}
      >
        Save instructions
      </button>
      {done && (
        <Notice>
          {connected
            ? "Instructions applied for the next reply."
            : "Instructions saved for the next start."}
        </Notice>
      )}
    </Section>
  );
}
