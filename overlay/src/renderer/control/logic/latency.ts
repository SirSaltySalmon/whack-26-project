/* Reads the brain's latency log lines into numbers for the Latency tab. Pure, so it's tested. */

export type LatencyKind =
  | "frame to bark"
  | "frame to first audio"
  | "event to bark"
  | "end of turn to first audio"
  | "player turn"
  | "event loop stall";

/** Table order: what happens on screen first, then the player's turns, then the loop's health. */
const KIND_ORDER: readonly LatencyKind[] = [
  "frame to bark",
  "frame to first audio",
  "event to bark",
  "end of turn to first audio",
  "player turn",
  "event loop stall",
];

/** Starting values, in ms: a value at or over its target missed it. Kinds left out have none. */
export const LATENCY_TARGETS_MS: Readonly<
  Partial<Record<LatencyKind, number>>
> = {
  "frame to bark": 1000,
  "event to bark": 300,
  "end of turn to first audio": 1000,
  "event loop stall": 100,
};

/** How many frame-to-voice reactions the tab lists. */
export const RECENT_REACTIONS = 10;

/** One time the partner spoke because of something on screen. */
export interface Reaction {
  /** The log line's clock time, or "" if it had none. */
  time: string;
  kind: "frame to bark" | "frame to first audio";
  event: string;
  /** What noticed it, such as `reader` or `observer`. */
  source: string;
  totalMs: number;
  noticedMs: number;
  spokeMs: number;
}

interface Series {
  kind: LatencyKind;
  source: string | null;
  /** In the order they were logged. */
  values: number[];
}

export interface LatencyState {
  /** Keyed by kind, plus the source for frame kinds, since a reader and the observer differ a lot. */
  series: Readonly<Record<string, Series>>;
  /** Newest first. */
  reactions: readonly Reaction[];
  /** From the line the brain logs as it stops. */
  loopSummary: { longestMs: number; overS: number } | null;
}

export const EMPTY_LATENCY: LatencyState = {
  series: {},
  reactions: [],
  loopSummary: null,
};

export type LatencyLine =
  | { type: "launch" }
  | { type: "sample"; kind: LatencyKind; ms: number }
  | { type: "reaction"; reaction: Reaction }
  | { type: "loop summary"; longestMs: number; overS: number };

// A sign, because `%.0f` prints a tiny negative clock difference as "-0".
const NUM = String.raw`(-?\d+(?:\.\d+)?)`;
// Matched anywhere, because verbose mode adds a date, level and logger name before the message.
const SAMPLES: readonly [RegExp, LatencyKind][] = [
  [new RegExp(`Latency: player turn took ${NUM} ms`), "player turn"],
  [new RegExp(`Latency: event to bark ${NUM} ms`), "event to bark"],
  [
    new RegExp(`Latency: end of turn to first audio ${NUM} ms`),
    "end of turn to first audio",
  ],
  [new RegExp(`Event loop stalled ${NUM} ms`), "event loop stall"],
];
const REACTION = new RegExp(
  `Latency: (frame to bark|frame to first audio) ${NUM} ms ` +
    `\\((.+?) from (\\S+): noticed in ${NUM}, spoke in ${NUM}\\)`,
);
const LOOP_SUMMARY = new RegExp(
  `Event loop: longest stall ${NUM} ms over ${NUM} s`,
);
const CLOCK = /^(?:\d{4}-\d{2}-\d{2} )?(\d{1,2}:\d{2}:\d{2})/;
// The Control Center logs the command line as it starts the brain, so this marks a new run.
const LAUNCH = /^> .*\s-m brain(\s|$)/;

export function parseLatencyLine(line: string): LatencyLine | null {
  if (LAUNCH.test(line)) return { type: "launch" };
  const reaction = REACTION.exec(line);
  if (reaction) {
    const [, kind, total, event, source, noticed, spoke] = reaction;
    return {
      type: "reaction",
      reaction: {
        time: CLOCK.exec(line)?.[1] ?? "",
        kind:
          kind === "frame to bark" ? "frame to bark" : "frame to first audio",
        event: event ?? "",
        source: source ?? "",
        totalMs: Number(total),
        noticedMs: Number(noticed),
        spokeMs: Number(spoke),
      },
    };
  }
  const summary = LOOP_SUMMARY.exec(line);
  if (summary) {
    return {
      type: "loop summary",
      longestMs: Number(summary[1]),
      overS: Number(summary[2]),
    };
  }
  for (const [pattern, kind] of SAMPLES) {
    const match = pattern.exec(line);
    if (match) return { type: "sample", kind, ms: Number(match[1]) };
  }
  return null;
}

const seriesKey = (kind: LatencyKind, source: string | null): string =>
  source === null ? kind : `${kind} · ${source}`;

/** Folds new log lines in. A launch line starts over, so numbers are since the brain started. */
export function addLines(
  state: LatencyState,
  lines: readonly string[],
): LatencyState {
  // Copied once per batch, so earlier states handed to React never change.
  let series: Record<string, Series> = { ...state.series };
  const copied = new Set<string>();
  let reactions = [...state.reactions];
  let loopSummary = state.loopSummary;

  const record = (kind: LatencyKind, source: string | null, ms: number) => {
    const key = seriesKey(kind, source);
    const current = series[key];
    if (!current) {
      series[key] = { kind, source, values: [ms] };
    } else if (copied.has(key)) {
      current.values.push(ms);
    } else {
      series[key] = { ...current, values: [...current.values, ms] };
    }
    copied.add(key);
  };

  for (const line of lines) {
    const parsed = parseLatencyLine(line);
    if (!parsed) continue;
    if (parsed.type === "launch") {
      series = {};
      copied.clear();
      reactions = [];
      loopSummary = null;
    } else if (parsed.type === "sample") {
      record(parsed.kind, null, parsed.ms);
    } else if (parsed.type === "reaction") {
      const { reaction } = parsed;
      record(reaction.kind, reaction.source, reaction.totalMs);
      reactions = [reaction, ...reactions].slice(0, RECENT_REACTIONS);
    } else {
      loopSummary = { longestMs: parsed.longestMs, overS: parsed.overS };
    }
  }
  return { series, reactions, loopSummary };
}

/** Nearest rank, so the answer is always a time that really happened. Null for no values. */
export function percentile(
  values: readonly number[],
  p: number,
): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const rank = Math.ceil((p / 100) * sorted.length);
  return sorted[Math.min(Math.max(rank, 1), sorted.length) - 1] ?? null;
}

export interface LatencyRow {
  key: string;
  kind: LatencyKind;
  source: string | null;
  count: number;
  lastMs: number;
  p50Ms: number;
  p95Ms: number;
  targetMs: number | null;
}

export function latencyRows(state: LatencyState): LatencyRow[] {
  return Object.entries(state.series)
    .map(([key, { kind, source, values }]) => ({
      key,
      kind,
      source,
      count: values.length,
      lastMs: values[values.length - 1] ?? 0,
      p50Ms: percentile(values, 50) ?? 0,
      p95Ms: percentile(values, 95) ?? 0,
      targetMs: LATENCY_TARGETS_MS[kind] ?? null,
    }))
    .sort(
      (a, b) =>
        KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind) ||
        (a.source ?? "").localeCompare(b.source ?? ""),
    );
}

export function missesTarget(ms: number, targetMs: number | null): boolean {
  return targetMs !== null && ms >= targetMs;
}

export const formatMs = (ms: number): string => `${Math.round(ms)} ms`;

export interface LoopHealth {
  stalls: number;
  longestMs: number | null;
  /** How long the loop was watched, known only once the brain has stopped. */
  overS: number | null;
}

export function loopHealth(state: LatencyState): LoopHealth {
  const stalls = state.series["event loop stall"]?.values ?? [];
  const longest = Math.max(
    ...stalls,
    state.loopSummary?.longestMs ?? -Infinity,
  );
  return {
    stalls: stalls.length,
    longestMs: Number.isFinite(longest) ? longest : null,
    overS: state.loopSummary?.overS ?? null,
  };
}

/**
 * The lines in `next` that `prev` didn't have. The Control Center's log only grows, dropping its
 * oldest lines past a cap, so `next` starts with some tail of `prev`; the longest such tail wins.
 */
export function newLines(
  prev: readonly string[],
  next: readonly string[],
): readonly string[] {
  if (prev === next) return [];
  for (
    let added = Math.max(0, next.length - prev.length);
    added < next.length;
    added++
  ) {
    const kept = next.length - added;
    const offset = prev.length - kept;
    let same = true;
    for (let i = 0; i < kept && same; i++) same = prev[offset + i] === next[i];
    if (same) return next.slice(kept);
  }
  return next;
}
