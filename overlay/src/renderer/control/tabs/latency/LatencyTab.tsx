import { Notice, Section } from "../../components/ui.tsx";
import { useControl } from "../../ControlContext.tsx";
import {
  formatMs,
  LATENCY_TARGETS_MS,
  latencyRows,
  loopHealth,
  missesTarget,
  type LatencyKind,
} from "../../logic/latency.ts";
import { LatestReaction, RecentReactions } from "./Reactions.tsx";
import { useLatency } from "./useLatency.ts";
import "./latency.css";

const label = (kind: LatencyKind): string =>
  kind.charAt(0).toUpperCase() + kind.slice(1);

function MsCell({ ms, target }: { ms: number; target: number | null }) {
  const over = missesTarget(ms, target);
  return (
    <td
      className={`lat-num${over ? " lat-over" : ""}`}
      title={over ? `At or over the ${target} ms target` : undefined}
    >
      {formatMs(ms)}
    </td>
  );
}

function Stat({
  name,
  value,
  over = false,
}: {
  name: string;
  value: string;
  over?: boolean;
}) {
  return (
    <div className="lat-stat">
      <span className="cc-hint">{name}</span>
      <span className={`lat-stat-value${over ? " lat-over" : ""}`}>
        {value}
      </span>
    </div>
  );
}

export function LatencyTab() {
  const control = useControl();
  const { state, clear } = useLatency(control.logs);
  const rows = latencyRows(state);
  const loop = loopHealth(state);
  const stallTarget = LATENCY_TARGETS_MS["event loop stall"] ?? null;

  return (
    <div className="cc-page">
      {control.external && (
        <Notice tone="warn">
          This partner was started outside the Control Center, so its log isn't
          here and neither are these numbers. Start it from here to see them.
        </Notice>
      )}

      <LatestReaction reaction={state.reactions[0]} />

      <Section
        title="By kind"
        hint="Since the partner started. p50 is the typical time, p95 the slow end. Amber is at or over target."
        aside={
          <button
            className="cc-button cc-button-quiet"
            type="button"
            onClick={clear}
          >
            Clear
          </button>
        }
      >
        {rows.length === 0 ? (
          <p className="cc-hint">No latency lines in the log yet.</p>
        ) : (
          <table className="lat-table">
            <thead>
              <tr>
                <th>Kind</th>
                <th className="lat-num">Last</th>
                <th className="lat-num">p50</th>
                <th className="lat-num">p95</th>
                <th className="lat-num">Count</th>
                <th className="lat-num">Target</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key}>
                  <td>
                    {label(row.kind)}
                    {row.source && (
                      <span className="cc-hint"> · {row.source}</span>
                    )}
                  </td>
                  <MsCell ms={row.lastMs} target={row.targetMs} />
                  <MsCell ms={row.p50Ms} target={row.targetMs} />
                  <MsCell ms={row.p95Ms} target={row.targetMs} />
                  <td className="lat-num">{row.count}</td>
                  <td className="lat-num lat-target">
                    {row.targetMs === null ? "—" : `< ${row.targetMs} ms`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <RecentReactions reactions={state.reactions} />

      <Section
        title="Event loop"
        hint="The brain warns when its event loop wakes up late. A stall holds up speech and barks too."
      >
        <div className="lat-stats">
          <Stat name="Stalls" value={String(loop.stalls)} />
          <Stat
            name="Longest"
            value={loop.longestMs === null ? "—" : formatMs(loop.longestMs)}
            over={
              loop.longestMs !== null &&
              missesTarget(loop.longestMs, stallTarget)
            }
          />
          {loop.overS !== null && (
            <Stat name="Watched for" value={`${Math.round(loop.overS)} s`} />
          )}
        </div>
        {loop.longestMs === null && (
          <p className="cc-hint">
            No stalls logged. The longest wake-up shows once the partner stops.
          </p>
        )}
      </Section>
    </div>
  );
}
