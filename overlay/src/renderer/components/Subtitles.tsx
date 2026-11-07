import type { SubtitleLine } from "../logic/subtitles.ts";

/** Click-through, and masked like everything else so the AI can't read its own words. */
export function Subtitles({ line }: { line: SubtitleLine | null }) {
  if (line === null || line.text === "") return null;
  return (
    <div
      // A new line gets a new element, or it would inherit the last line's fade part way through.
      key={line.utteranceId}
      className={`subtitles${line.done ? " subtitles-done" : ""}`}
      data-rect-id="subtitles"
    >
      {line.text}
    </div>
  );
}
