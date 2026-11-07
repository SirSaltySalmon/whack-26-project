import type { SubtitleLine } from "../logic/subtitles.ts";

/** Click-through, and masked like everything else so the AI can't read its own words. */
export function Subtitles({ line }: { line: SubtitleLine | null }) {
  if (line === null || line.text === "") return null;
  return (
    <div
      className={`subtitles${line.done ? " subtitles-done" : ""}`}
      data-rect-id="subtitles"
    >
      {line.text}
    </div>
  );
}
