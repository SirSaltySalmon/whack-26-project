import { Pill, Section } from "../../components/ui.tsx";
import {
  formatMs,
  LATENCY_TARGETS_MS,
  missesTarget,
  type Reaction,
} from "../../logic/latency.ts";

const targetOf = (reaction: Reaction): number | null =>
  LATENCY_TARGETS_MS[reaction.kind] ?? null;

const voiceOf = (reaction: Reaction): string =>
  reaction.kind === "frame to bark" ? "bark" : "speech";

/** The newest frame-to-voice time, big, so judges can read it from across the room. */
export function LatestReaction({
  reaction,
}: {
  reaction: Reaction | undefined;
}) {
  if (!reaction) {
    return (
      <Section
        title="Latest reaction"
        hint="When the partner speaks about something it saw on screen, the time from that frame to its voice shows here."
      >
        <p className="lat-hero-total lat-empty">— ms</p>
      </Section>
    );
  }
  const target = targetOf(reaction);
  const over = missesTarget(reaction.totalMs, target);
  return (
    <Section
      title="Latest reaction"
      hint="From the frame that showed it to the partner's voice."
      aside={
        target !== null && (
          <Pill tone={over ? "warn" : "on"}>
            {over ? "Over" : "Under"} the {target} ms target
          </Pill>
        )
      }
    >
      <div className="lat-hero">
        <span className={`lat-hero-total${over ? " lat-over" : ""}`}>
          {formatMs(reaction.totalMs)}
        </span>
        <div className="lat-hero-what">
          <strong>{reaction.event}</strong>
          <span className="cc-hint">
            seen by the {reaction.source}, answered with{" "}
            {reaction.kind === "frame to bark" ? "a bark" : "speech"}
            {reaction.time && ` · ${reaction.time}`}
          </span>
        </div>
      </div>
      <div
        className="lat-split"
        role="img"
        aria-label={`Noticed in ${formatMs(reaction.noticedMs)}, spoke in ${formatMs(reaction.spokeMs)}`}
      >
        <span
          className="lat-split-noticed"
          style={{ flexGrow: Math.max(0, reaction.noticedMs) }}
        />
        <span
          className="lat-split-spoke"
          style={{ flexGrow: Math.max(0, reaction.spokeMs) }}
        />
      </div>
      <div className="lat-legend">
        <span>
          <i className="lat-dot lat-split-noticed" aria-hidden />
          Noticed in {formatMs(reaction.noticedMs)}
        </span>
        <span>
          <i className="lat-dot lat-split-spoke" aria-hidden />
          Spoke in {formatMs(reaction.spokeMs)}
        </span>
      </div>
    </Section>
  );
}

export function RecentReactions({
  reactions,
}: {
  reactions: readonly Reaction[];
}) {
  return (
    <Section
      title="Recent reactions"
      hint="Newest first. Noticed is the time to see it, spoke the time from then to voice."
    >
      {reactions.length === 0 ? (
        <p className="cc-hint">None yet.</p>
      ) : (
        <table className="lat-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Event</th>
              <th>Seen by</th>
              <th>Voice</th>
              <th className="lat-num">Noticed</th>
              <th className="lat-num">Spoke</th>
              <th className="lat-num">Total</th>
            </tr>
          </thead>
          <tbody>
            {reactions.map((reaction, index) => {
              const target = targetOf(reaction);
              const over = missesTarget(reaction.totalMs, target);
              return (
                // Reactions have no ids; the list is only ever replaced whole.
                <tr key={index}>
                  <td className="lat-time">{reaction.time}</td>
                  <td>{reaction.event}</td>
                  <td>{reaction.source}</td>
                  <td>{voiceOf(reaction)}</td>
                  <td className="lat-num">{formatMs(reaction.noticedMs)}</td>
                  <td className="lat-num">{formatMs(reaction.spokeMs)}</td>
                  <td
                    className={`lat-num${over ? " lat-over" : ""}`}
                    title={
                      over ? `At or over the ${target} ms target` : undefined
                    }
                  >
                    {formatMs(reaction.totalMs)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Section>
  );
}
