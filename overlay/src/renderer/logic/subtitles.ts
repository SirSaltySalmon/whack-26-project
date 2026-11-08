import type { SubtitleChunk } from "../../lib/protocol.generated.ts";

export interface SubtitleLine {
  utteranceId: string;
  text: string;
  /** The utterance has ended, so the line can fade. */
  done: boolean;
}

/** Word timings can arrive as bare words, so this adds the spaces, but not before punctuation. */
function joinWords(previous: string, next: string): string {
  if (previous === "" || next === "") return previous + next;
  if (/\s$/.test(previous) || /^[\s.,!?;:'’)]/.test(next)) {
    return previous + next;
  }
  return `${previous} ${next}`;
}

/**
 * Ends a line that has stopped growing without its `final` chunk, as when speech fails and never
 * plays. Only the line it was started for, and only if nothing has ended it already.
 */
export function endStaleSubtitle(
  current: SubtitleLine | null,
  utteranceId: string,
): SubtitleLine | null {
  if (current === null || current.done || current.utteranceId !== utteranceId) {
    return current;
  }
  return { ...current, done: true };
}

/**
 * Real voice sends words as `final=false` chunks, then an empty `final=true` chunk. Subtitles-only
 * mode sends one chunk with the whole text and `final=true`. Both end with `done` set.
 */
export function applySubtitle(
  current: SubtitleLine | null,
  chunk: SubtitleChunk,
): SubtitleLine | null {
  const final = chunk.final ?? false;
  const same = current?.utteranceId === chunk.utterance_id;
  // An interrupted utterance can end after a new one has begun, and mustn't end the new one.
  if (!same && chunk.text === "") return current;
  return {
    utteranceId: chunk.utterance_id,
    text: same ? joinWords(current.text, chunk.text) : chunk.text,
    done: final,
  };
}
