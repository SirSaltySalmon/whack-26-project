import { useCallback, useEffect, useState } from "react";
import { Notice, Pill, Section, Toggle } from "../../components/ui.tsx";
import { useControl } from "../../ControlContext.tsx";
import { ago, groupFacts, SOURCE_LABEL } from "../../logic/memory.ts";
import { FactGroupCard } from "./FactGroupCard.tsx";
import { GamePicker } from "./GamePicker.tsx";
import { useMemoryGames } from "./useMemoryGames.ts";
import { useMemoryQuery } from "./useMemoryQuery.ts";

import { MemoryManager } from "./MemoryManager.tsx";
import { InstructionsEditor } from "./InstructionsEditor.tsx";

export function MemoryTab() {
  const { connected, process, stop, external } = useControl();
  const stopped = !connected && ["stopped", "crashed"].includes(process.state);
  const [revision, setRevision] = useState(0);
  const onUpdated = useCallback(() => setRevision((value) => value + 1), []);
  return (
    <div className="cc-page mem-page">
      <InstructionsEditor />
      <ReviewMemory key={revision} />
      <details>
        <summary>Add, edit or clear saved memory</summary>
        {stopped ? (
          <MemoryManager onUpdated={onUpdated} />
        ) : (
          <Section
            title="Edit or clear memory"
            hint="Stop the brain before editing so a running turn cannot restore old memories. Managing saved memory uses no API tokens."
          >
            {external ? (
              <Notice>
                Stop the brain in its terminal to manage saved memory here.
              </Notice>
            ) : (
              <button className="cc-button" type="button" onClick={stop}>
                Stop brain to manage memory
              </button>
            )}
          </Section>
        )}
      </details>
    </div>
  );
}

const count = (n: number, noun: string): string =>
  `${n} ${noun}${n === 1 ? "" : "s"}`;

function ReviewMemory() {
  const { connected } = useControl();
  const [text, setText] = useState("");
  const [history, setHistory] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const games = useMemoryGames();
  // Starting or stopping the partner moves the view to the game it's filing memory under.
  useEffect(() => setPicked(null), [connected]);
  const game = picked ?? games.list?.current ?? null;
  const playing = connected && games.list?.live ? games.list.current : null;
  const memory = useMemoryQuery(text, history, game);
  const results = memory.results;
  const groups = groupFacts(results?.facts ?? []);
  const error = memory.error ?? games.error;
  const refresh = () => {
    games.refresh();
    memory.refresh();
  };

  return (
    <div className="cc-page mem-page">
      <div className="mem-toolbar">
        <GamePicker
          games={games.list?.games ?? []}
          value={game}
          playing={playing ?? null}
          onChange={setPicked}
        />
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
        <button className="cc-button" type="button" onClick={refresh}>
          Refresh
        </button>
      </div>

      {results && (
        <p className="cc-hint mem-stats">
          {count(results.facts.length, "fact")} ·{" "}
          {count(results.questions.length, "question")} ·{" "}
          {count(results.notes.length, "note")} · searched in{" "}
          {results.elapsed_ms} ms (SQLite FTS5)
          {!connected && " · partner off, reading saved memory"}
        </p>
      )}
      {memory.lastToast && (
        <Notice>
          <Pill tone={memory.lastToast.source}>
            {SOURCE_LABEL[memory.lastToast.source]}
          </Pill>{" "}
          {memory.lastToast.text}
        </Notice>
      )}
      {error && <Notice tone="warn">Memory didn't answer: {error}</Notice>}

      <div className="mem-columns">
        <Section
          title="What the partner knows"
          className="mem-facts"
          hint="Every fact keeps its source and confidence. You beat the screen, the screen beats the wiki, and nothing is overwritten: old values are closed with the time they stopped being true."
        >
          <div className="mem-fact-list" aria-label="Facts">
            {!results && !error && <p className="cc-empty-line">Loading…</p>}
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
          </div>
        </Section>

        <aside className="mem-side">
          <Section
            title="What it would recall"
            hint={
              <>
                The exact context the talker gets for{" "}
                {text ? "this search" : "a turn"}
                {game !== null && game === playing
                  ? " right now"
                  : ", as the next session of this game would start"}
                : small and pre-assembled, never the raw session.
              </>
            }
          >
            {memory.recall ? (
              <>
                <pre className="mem-recall">
                  {memory.recall.context || "(nothing)"}
                </pre>
                <p className="cc-hint mem-meta">
                  {memory.recall.context.length} characters · built in{" "}
                  {memory.recall.elapsed_ms} ms
                </p>
              </>
            ) : (
              <p className="cc-hint">Loading…</p>
            )}
          </Section>

          <Section title="Questions for you">
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
          </Section>

          <Section title="Session notes">
            {results?.notes.length ? (
              results.notes.map((note) => (
                <details key={note.id} className="mem-note">
                  <summary>
                    {note.kind === "recap" ? "Recap" : "Rolling note"}
                    <span className="mem-meta">{ago(note.created_at)}</span>
                  </summary>
                  <pre>{note.body}</pre>
                </details>
              ))
            ) : (
              <p className="cc-hint">Written every few minutes of play.</p>
            )}
          </Section>
        </aside>
      </div>
    </div>
  );
}
