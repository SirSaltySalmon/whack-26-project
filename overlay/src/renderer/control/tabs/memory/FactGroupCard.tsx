import type { FactView } from "../../../../lib/protocol.generated.ts";
import { Pill } from "../../components/ui.tsx";
import { ago, type FactGroup } from "../../logic/memory.ts";

const SOURCE_TITLE: Record<FactView["source"], string> = {
  player: "You said so. Beats anything else.",
  observed: "Seen on screen. Beats the wiki.",
  wiki: "From the wiki. Tentative until you or the screen confirm it.",
};

function Confidence({ value }: { value: number }) {
  const percent = Math.round(value * 100);
  return (
    <span className="mem-confidence" title={`Confidence ${percent}%`}>
      <span className="mem-confidence-bar">
        <span style={{ width: `${percent}%` }} />
      </span>
      {percent}%
    </span>
  );
}

function CurrentFact({ fact }: { fact: FactView }) {
  return (
    <div className="mem-fact">
      <span className="mem-value">{fact.value}</span>
      <Pill tone={fact.source} title={SOURCE_TITLE[fact.source]}>
        {fact.source}
      </Pill>
      <Confidence value={fact.confidence} />
      {fact.tentative && (
        <Pill tone="warn" title="Not confirmed by you or the screen yet">
          tentative
        </Pill>
      )}
      <span className="cc-hint mem-when">since {ago(fact.valid_from)}</span>
    </div>
  );
}

function PastFact({ fact }: { fact: FactView }) {
  return (
    <div
      className="mem-fact mem-fact-past"
      title="Closed, not deleted: memory never overwrites"
    >
      <span className="mem-value">{fact.value}</span>
      <span className="mem-source-text">{fact.source}</span>
      <span className="cc-hint mem-when">
        {ago(fact.valid_from)} → replaced{" "}
        {fact.valid_to ? ago(fact.valid_to) : ""}
      </span>
    </div>
  );
}

export function FactGroupCard({ group }: { group: FactGroup }) {
  return (
    <article
      className={`mem-group${group.conflict ? " mem-group-conflict" : ""}`}
    >
      <header className="mem-group-head">
        <span className="mem-subject">{group.subject}</span>
        <span className="mem-attribute">{group.attribute}</span>
        {group.conflict && (
          <Pill
            tone="warn"
            title="Trusted sources disagree, so the partner will ask you"
          >
            conflict: will ask you
          </Pill>
        )}
      </header>
      {group.current.map((fact) => (
        <CurrentFact key={fact.id} fact={fact} />
      ))}
      {group.current.length === 0 && (
        <p className="cc-hint">
          Nothing current: every value here was replaced.
        </p>
      )}
      {group.past.map((fact) => (
        <PastFact key={fact.id} fact={fact} />
      ))}
    </article>
  );
}
