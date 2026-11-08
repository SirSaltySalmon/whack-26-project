import { useCallback, useEffect, useState } from "react";
import type {
  AdminFact,
  MemoryAdminRequest,
  MemoryAdminResult,
} from "../../../../lib/protocol.generated.ts";
import { Field, Notice, Section } from "../../components/ui.tsx";
import { useControl } from "../../ControlContext.tsx";

export function MemoryManager({ onUpdated }: { onUpdated: () => void }) {
  const { manageMemory, config } = useControl();
  const [data, setData] = useState<MemoryAdminResult | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<AdminFact | null>(null);
  const [game, setGame] = useState(config.gameTitle);
  const [subject, setSubject] = useState("");
  const [attribute, setAttribute] = useState("");
  const [value, setValue] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const run = useCallback(
    async (request: MemoryAdminRequest) => {
      setBusy(true);
      setError("");
      setMessage("");
      try {
        const result = await manageMemory(request);
        setData(result);
        if (request.operation !== "list") {
          onUpdated();
          setMessage(
            result.backup
              ? `Memory cleared. Backup saved at ${result.backup}`
              : "Memory updated.",
          );
          setEditing(null);
          setValue("");
          setConfirmation("");
        }
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
      } finally {
        setBusy(false);
      }
    },
    [manageMemory, onUpdated],
  );
  useEffect(() => {
    void run({ operation: "list" });
  }, [run]);
  const edit = (fact: AdminFact) => {
    setEditing(fact);
    setGame(fact.game ?? "");
    setSubject(fact.subject);
    setAttribute(fact.attribute);
    setValue(fact.value);
  };

  return (
    <Section
      title="Manage saved memory"
      hint="Works locally with the brain stopped. No AI API calls. Changes apply on the next start."
    >
      {error && <Notice tone="warn">{error}</Notice>}
      {message && <Notice>{message}</Notice>}
      {data && (
        <p className="cc-hint">
          {data.total_facts} current facts · {data.notes} notes · {data.events}{" "}
          conversation/event records · {data.questions} questions. Database:{" "}
          {data.database}
        </p>
      )}
      <fieldset disabled={busy} className="mem-admin-fields">
        <button
          type="button"
          className="cc-button"
          onClick={() => void run({ operation: "list" })}
        >
          Refresh saved memory
        </button>
        <form
          className="cc-grid"
          onSubmit={(event) => {
            event.preventDefault();
            void run({
              operation: "remember",
              fact_id: editing?.id,
              game: game.trim() || null,
              subject,
              attribute,
              value,
            });
          }}
        >
          <Field label="Game (blank applies across games)">
            <input
              className="cc-input"
              value={game}
              disabled={!!editing}
              maxLength={200}
              onChange={(e) => setGame(e.target.value)}
            />
          </Field>
          <Field label="Subject, e.g. player">
            <input
              className="cc-input"
              value={subject}
              disabled={!!editing}
              required
              maxLength={200}
              onChange={(e) => setSubject(e.target.value)}
            />
          </Field>
          <Field label="Attribute, e.g. goal">
            <input
              className="cc-input"
              value={attribute}
              disabled={!!editing}
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
            {editing ? "Save correction" : "Add player fact"}
          </button>
          {editing && (
            <button
              className="cc-button"
              type="button"
              onClick={() => {
                setEditing(null);
                setValue("");
              }}
            >
              Cancel edit
            </button>
          )}
        </form>
        <p className="cc-hint">
          Corrections are recorded as player-confirmed with full confidence.
          Replaced and forgotten facts remain in history; forgetting prevents
          the same guess returning. Clear all removes history too.
        </p>
        <div className="mem-fact-list">
          {data?.facts.map((fact) => (
            <article className="mem-group" key={fact.id}>
              <p>
                {fact.game ?? "All games"} · {fact.subject} / {fact.attribute}:{" "}
                <strong>{fact.value}</strong>
              </p>
              <p className="cc-hint">
                {fact.source} · {Math.round(fact.confidence * 100)}% confidence
                {fact.tentative ? " · tentative" : ""}
              </p>
              <button
                type="button"
                className="cc-button"
                onClick={() => edit(fact)}
              >
                Edit
              </button>{" "}
              <button
                type="button"
                className="cc-button"
                onClick={() =>
                  void run({ operation: "forget", fact_id: fact.id })
                }
              >
                Forget
              </button>
            </article>
          ))}
          {data?.total_facts === 0 && <p>No saved facts.</p>}
          {!!data && data.total_facts > data.facts.length && (
            <p className="cc-hint">Showing the newest 200 current facts.</p>
          )}
        </div>
        <Section
          title="Clear all assistant memory"
          hint="Erases facts and their history, questions, notes and conversation/event records across all games. Keeps learned game profiles, settings and custom instructions. A database backup is saved first. Existing recordings and exported files are kept."
        >
          <Field label="Type CLEAR to confirm">
            <input
              className="cc-input"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              autoComplete="off"
            />
          </Field>
          <button
            className="cc-button"
            type="button"
            disabled={confirmation !== "CLEAR" || !data}
            onClick={() => void run({ operation: "clear", confirmation })}
          >
            Clear all memory
          </button>
        </Section>
      </fieldset>
    </Section>
  );
}
