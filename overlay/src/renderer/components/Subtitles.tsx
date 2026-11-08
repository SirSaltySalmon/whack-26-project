import { Fragment, useEffect, useRef, type CSSProperties } from "react";
import type { SubtitleLine } from "../logic/subtitles.ts";

// Words of one chunk arrive together, so a small stagger reads as speech without lagging the audio.
const WORD_STAGGER_MS = 45;

export type AvatarSide = "left" | "right";

function Line({
  line,
  speaker,
  avatarSide,
}: {
  line: SubtitleLine;
  speaker: string | null;
  avatarSide: AvatarSide;
}) {
  // How many words were already on screen, so only new ones are staggered from zero.
  const shown = useRef(0);
  const words = line.text.split(/\s+/).filter((word) => word !== "");
  const before = shown.current;
  useEffect(() => {
    shown.current = words.length;
  });

  return (
    <div
      className={`subtitles${line.done ? " subtitles-done" : ""}`}
      data-rect-id="subtitles"
      // Lets a skin aim a speech bubble's tail at the character.
      data-side={avatarSide}
    >
      <div className="subtitles-box">
        {speaker && <span className="subtitles-name">{speaker}</span>}
        <span className="subtitles-text">
          {words.map((word, index) => (
            // By position: a chunk that finishes a word updates it rather than replaying it.
            <Fragment key={index}>
              {index > 0 && " "}
              <span
                className="subtitles-word"
                style={
                  {
                    "--word-delay": `${Math.max(0, index - before) * WORD_STAGGER_MS}ms`,
                  } as CSSProperties
                }
              >
                {word}
              </span>
            </Fragment>
          ))}
        </span>
      </div>
    </div>
  );
}

/**
 * Click-through, and masked like everything else so the AI can't read its own words. Each word is
 * its own element so skins can animate words in as they're spoken.
 */
export function Subtitles({
  line,
  speaker,
  avatarSide,
}: {
  line: SubtitleLine | null;
  /** Who's talking, for skins that show a name tab. */
  speaker: string | null;
  /** Which half of the screen the character is on. */
  avatarSide: AvatarSide;
}) {
  if (line === null || line.text === "") return null;
  // A new line gets a new element, or it would inherit the last line's fade part way through.
  return (
    <Line
      key={line.utteranceId}
      line={line}
      speaker={speaker}
      avatarSide={avatarSide}
    />
  );
}
