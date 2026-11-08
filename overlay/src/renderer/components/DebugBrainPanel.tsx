import type { DebugBrain } from "../../lib/protocol.generated.ts";
import { formatMs, moodTone, speed, tail } from "../logic/debugBrain.ts";

interface DebugBrainPanelProps {
  brain: DebugBrain | null;
}

/**
 * What the brain hears, decides and does, in a corner while debugging. The whole panel carries a
 * data-rect-id, so the brain masks it: otherwise the observer would read its own transcript back
 * as text on the game's screen.
 */
export function DebugBrainPanel({ brain }: DebugBrainPanelProps) {
  if (brain === null) return null;
  const hearing = brain.hearing ?? "";
  const live = brain.hearing_live ?? false;
  const latency = brain.latency ?? [];
  const doing = [brain.doing, brain.focus ? `watching: ${brain.focus}` : null]
    .filter((part): part is string => Boolean(part))
    .join(" · ");
  return (
    <aside
      className="brain-panel"
      data-rect-id="debug-brain"
      aria-hidden="true"
    >
      <div className="brain-heading">
        <span className="brain-key">
          {live ? <span className="brain-live" /> : null}
          Hearing
        </span>
        {brain.mood ? (
          <span
            className={`brain-mood mood-${moodTone(brain.mood_valence ?? 0)}`}
          >
            {brain.mood}
          </span>
        ) : null}
      </div>
      <p className={live ? "brain-quote brain-quote-live" : "brain-quote"}>
        {hearing ? `“${tail(hearing)}”` : "…"}
      </p>
      <dl className="brain-rows">
        <dt className="brain-key">Decided</dt>
        <dd>{brain.decision ?? "—"}</dd>
        <dt className="brain-key">Doing</dt>
        <dd>{doing || "—"}</dd>
        <dt className="brain-key">Latency</dt>
        <dd className="brain-latency">
          {latency.length === 0
            ? "—"
            : latency.map((shown) => (
                <span key={shown.label} className="brain-timing">
                  <span className="brain-timing-label">{shown.label}</span>
                  <span className={`brain-timing-ms speed-${speed(shown.ms)}`}>
                    {formatMs(shown.ms)}
                  </span>
                </span>
              ))}
        </dd>
      </dl>
    </aside>
  );
}
