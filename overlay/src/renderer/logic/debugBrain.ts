/** Formatting for the debug panel's snapshot of what the brain hears, decides and does. */

export type MoodTone = "good" | "calm" | "bad";
export type Speed = "fast" | "ok" | "slow";

/** Past this either way, a mood reads as clearly good or bad rather than calm. */
const MOOD_THRESHOLD = 0.2;
/** CLAUDE.md's budgets: under 300 ms to a cached bark, under 1 s to the first audio of a reply. */
const FAST_MS = 300;
const OK_MS = 1000;
/** About two lines of the panel. Older words drop off the front, as they would in a caption. */
const HEARING_CHARS = 110;

export function moodTone(valence: number): MoodTone {
  if (valence >= MOOD_THRESHOLD) return "good";
  if (valence <= -MOOD_THRESHOLD) return "bad";
  return "calm";
}

export function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function speed(ms: number): Speed {
  if (ms <= FAST_MS) return "fast";
  if (ms <= OK_MS) return "ok";
  return "slow";
}

/** The newest words of what was heard, from a word boundary, so a long turn still fits. */
export function tail(text: string, max: number = HEARING_CHARS): string {
  const clean = text.replace(/\s+/g, " ").trim();
  if (clean.length <= max) return clean;
  const cut = clean.slice(clean.length - max);
  const space = cut.indexOf(" ");
  const start = space >= 0 && space < 20 ? cut.slice(space + 1) : cut;
  return `…${start}`;
}
