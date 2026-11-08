/* The player's pacing settings: how often the partner speaks up unasked. Pure, so the launcher,
   the Pacing tab and tests share it. */
import type { Pacing } from "./protocol.generated.ts";

export type PacingKey = keyof Pacing;
/** The generated type marks defaulted fields optional; this one has them all. */
export type FullPacing = Required<Pacing>;

/** Matches the brain's defaults in shared/protocol/messages.py. */
export const DEFAULT_PACING: FullPacing = {
  event_gap_s: 8,
  question_gap_s: 45,
  question_quiet_s: 0,
  advice_first_s: 45,
  advice_gap_s: 90,
  advice_quiet_s: 10,
};

/** The brain only refuses negatives. These caps keep a typo from silencing it for hours. */
export const PACING_MAX: FullPacing = {
  event_gap_s: 120,
  question_gap_s: 1800,
  question_quiet_s: 300,
  advice_first_s: 1800,
  advice_gap_s: 1800,
  advice_quiet_s: 300,
};

const KEYS = Object.keys(DEFAULT_PACING) as PacingKey[];

export function clampPacing(key: PacingKey, value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_PACING[key];
  return Math.min(Math.max(value, 0), PACING_MAX[key]);
}

/** Saved files can be old or hand-edited, so every field falls back to its default. */
export function fullPacing(raw: unknown): FullPacing {
  const saved =
    typeof raw === "object" && raw !== null && !Array.isArray(raw)
      ? (raw as Record<string, unknown>)
      : {};
  const result = { ...DEFAULT_PACING };
  for (const key of KEYS) {
    const value = saved[key];
    if (typeof value === "number") result[key] = clampPacing(key, value);
  }
  return result;
}

export function samePacing(a: FullPacing, b: FullPacing): boolean {
  return KEYS.every((key) => a[key] === b[key]);
}

export interface PacingPreset {
  name: string;
  pacing: FullPacing;
}

export const PACING_PRESETS: readonly PacingPreset[] = [
  {
    name: "Lively",
    pacing: {
      event_gap_s: 8,
      question_gap_s: 20,
      question_quiet_s: 0,
      advice_first_s: 20,
      advice_gap_s: 45,
      advice_quiet_s: 5,
    },
  },
  { name: "Default", pacing: DEFAULT_PACING },
  {
    // The timings before pacing became a setting.
    name: "Calm",
    pacing: {
      event_gap_s: 8,
      question_gap_s: 90,
      question_quiet_s: 20,
      advice_first_s: 90,
      advice_gap_s: 180,
      advice_quiet_s: 20,
    },
  },
];
