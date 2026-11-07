import { useEffect, useRef, useState } from "react";
import { useControl } from "../../ControlContext.tsx";

type Tone = "error" | "warn" | "latency" | "you" | "plain";

/** Colours what matters on stage: failures, and how fast each turn was. */
function toneOf(line: string): Tone {
  if (line.startsWith("you> ")) return "you";
  if (/\b(ERROR|CRITICAL|Traceback)\b/.test(line)) return "error";
  // A traceback's body: indented frames and source, and the exception line that ends it.
  if (/^\s+\S|^[\w.]+(Error|Exception)\b/.test(line)) return "error";
  if (/\bWARNING\b/.test(line)) return "warn";
  if (/\b\d+(\.\d+)?\s?ms\b|latency/i.test(line)) return "latency";
  return "plain";
}

export function ConsoleTab() {
  const control = useControl();
  const [filter, setFilter] = useState("");
  const [turn, setTurn] = useState("");
  const [follow, setFollow] = useState(true);
  const end = useRef<HTMLDivElement>(null);
  const canType = control.config.typed && control.process.state === "running";

  const needle = filter.trim().toLowerCase();
  const lines = needle
    ? control.logs.filter((line) => line.toLowerCase().includes(needle))
    : control.logs;

  useEffect(() => {
    if (follow) end.current?.scrollIntoView({ block: "end" });
  }, [lines.length, follow]);

  return (
    <div className="cc-page console-page">
      <div className="console-toolbar">
        <input
          className="cc-input"
          type="search"
          value={filter}
          placeholder="Filter: latency, observer, wiki…"
          spellCheck={false}
          onChange={(event) => setFilter(event.target.value)}
        />
        <label className="console-follow">
          <input
            type="checkbox"
            checked={follow}
            onChange={(event) => setFollow(event.target.checked)}
          />
          Follow
        </label>
      </div>

      <div className="console-log" role="log" aria-live="off">
        {lines.length === 0 && (
          <p className="cc-hint">
            The partner's log shows here once it starts.
          </p>
        )}
        {lines.map((line, index) => (
          // Lines have no ids and never reorder, so the index is stable enough.
          <div key={index} className={`console-line console-${toneOf(line)}`}>
            {line}
          </div>
        ))}
        <div ref={end} />
      </div>

      <form
        className="console-type"
        onSubmit={(event) => {
          event.preventDefault();
          if (!turn.trim()) return;
          control.typeTurn(turn);
          setTurn("");
        }}
      >
        <input
          className="cc-input"
          value={turn}
          disabled={!canType}
          placeholder={
            canType
              ? "Say something to the partner, as if you'd spoken it"
              : "Turn on Typed turns in Agent and start the partner to type here"
          }
          onChange={(event) => setTurn(event.target.value)}
        />
        <button
          className="cc-button cc-button-primary"
          type="submit"
          disabled={!canType}
        >
          Send
        </button>
      </form>
    </div>
  );
}
