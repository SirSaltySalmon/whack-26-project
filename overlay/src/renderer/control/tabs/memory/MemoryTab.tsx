import { useState } from "react";
import { Notice, Pill, Toggle } from "../../components/ui.tsx";
import { ago, groupFacts } from "../../logic/memory.ts";
import { FactGroupCard } from "./FactGroupCard.tsx";
import { useMemoryQuery } from "./useMemoryQuery.ts";

const count = (n: number, noun: string): string =>
  `${n} ${noun}${n === 1 ? "" : "s"}`;

export function MemoryTab() {
  const [text, setText] = useState("");
  const [history, setHistory] = useState(false);
  const memory = useMemoryQuery(text, history);
  const results = memory.results;
  const groups = groupFacts(results?.facts ?? []);

  return (
    <div className="cc-page mem-page">
      <div className="mem-toolbar">
        <input
          className="cc-input mem-search"
          type="search"
          value={text}
          placeholder="Search memory: weapon, boss, goal…"
          spellCheck={false}
          onChange={(event) => setText(event.target.value)}
        />
        <Toggle
          label="History"
          hint="Show what each fact replaced"
          on={history}
          onChange={setHistory}
        />
        <button className="cc-button" type="button" onClick={memory.refresh}>
          Refresh
        </button>
      </div>

      {results && (
        <p className="cc-hint mem-stats">
          {count(results.facts.length, "fact")} ·{" "}
          {count(results.questions.length, "question")} ·{" "}
          {count(results.notes.length, "note")} · searched in{" "}
          {results.elapsed_ms} ms (SQLite FTS5)
        </p>
      )}
      {memory.lastToast && (
        <Notice>
          <Pill tone={memory.lastToast.source}>{memory.lastToast.source}</Pill>{" "}
          {memory.lastToast.text}
        </Notice>
      )}
      {memory.error && (
        <Notice tone="warn">Memory didn't answer: {memory.error}</Notice>
      )}

      <div className="mem-columns">
        <section className="mem-facts" aria-label="Facts">
          <h2>What the partner knows</h2>
          <p className="cc-hint">
            Every fact keeps its source and confidence. You beat the screen, the
            screen beats the wiki, and nothing is overwritten: old values are
            closed with the time they stopped being true.
          </p>
          {groups.length === 0 && results && (
            <p className="cc-empty-line">
              {text
                ? "Nothing matches."
                : "Nothing remembered yet. Tell the partner about yourself."}
            </p>
          )}
          {groups.map((group) => (
            <FactGroupCard key={group.key} group={group} />
          ))}
        </section>

        <aside className="mem-side">
          <section className="mem-panel">
            <h2>What it would recall</h2>
            <p className="cc-hint">
              The exact context the talker gets for{" "}
              {text ? "this search" : "a turn right now"}: small and
              pre-assembled, never the raw session.
            </p>
            {memory.recall ? (
              <>
                <pre className="mem-recall">
                  {memory.recall.context || "(nothing)"}
                </pre>
                <p className="cc-hint">
                  {memory.recall.context.length} characters · built in{" "}
                  {memory.recall.elapsed_ms} ms
                </p>
              </>
            ) : (
              <p className="cc-hint">Loading…</p>
            )}
          </section>

          <section className="mem-panel">
            <h2>Questions for you</h2>
            {results?.questions.length ? (
              <ul className="mem-list">
                {results.questions.map((question) => (
                  <li key={question.id}>
                    <span>{question.text}</span>
                    {question.status !== "open" && (
                      <Pill tone="off">
                        {question.status}
                        {question.answer ? `: ${question.answer}` : ""}
                      </Pill>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="cc-hint">
                None open. When unsure, it asks instead of guessing.
              </p>
            )}
          </section>

          <section className="mem-panel">
            <h2>Session notes</h2>
            {results?.notes.length ? (
              results.notes.map((note) => (
                <details key={note.id} className="mem-note">
                  <summary>
                    {note.kind === "recap" ? "Recap" : "Rolling note"} ·{" "}
                    {ago(note.created_at)}
                  </summary>
                  <pre>{note.body}</pre>
                </details>
              ))
            ) : (
              <p className="cc-hint">Written every few minutes of play.</p>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
