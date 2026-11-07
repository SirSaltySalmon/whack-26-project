import type { State } from "../../lib/protocol.generated.ts";
import { useFrameGesture } from "../hooks/useFrameGesture.ts";
import { useHovered } from "../hooks/useHovered.ts";
import {
  AVATAR_LIMITS,
  moveFrame,
  resizeFrame,
  type Frame,
} from "../logic/layout.ts";

/** Placeholder until there's art. Swap this for an image or animation in the same 3:4 frame. */
function AvatarArt({ state }: { state: State }) {
  return <div className="avatar-art" data-state={state} />;
}

interface AvatarProps {
  frame: Frame;
  state: State;
  onFrame(frame: Frame): void;
  onFrameEnd(frame: Frame): void;
  /** Reopens the wiki window. Null when there's nothing to reopen. */
  onOpenWiki: (() => void) | null;
}

/**
 * The body isn't marked interactive, so clicks on it reach the game even while the controls show:
 * the game aims with the mouse. Hover still works because the window forwards mouse moves.
 */
export function Avatar({
  frame,
  state,
  onFrame,
  onFrameEnd,
  onOpenWiki,
}: AvatarProps) {
  const startMove = useFrameGesture({
    frame,
    change: moveFrame,
    onFrame,
    onEnd: onFrameEnd,
  });
  const startResize = useFrameGesture({
    frame,
    change: (start, dx, dy, viewport) =>
      resizeFrame(start, dx, dy, viewport, AVATAR_LIMITS),
    onFrame,
    onEnd: onFrameEnd,
  });

  const hovered = useHovered(frame);

  return (
    <div
      className={`avatar${hovered ? " avatar-hovered" : ""}`}
      data-rect-id="avatar"
      style={{
        left: frame.x,
        top: frame.y,
        width: frame.width,
        height: frame.height,
      }}
    >
      <AvatarArt state={state} />
      <div className="avatar-controls">
        <div
          className="avatar-grip"
          data-interactive
          title="Drag to move"
          onPointerDown={startMove}
        />
        {onOpenWiki && (
          <button
            className="avatar-wiki"
            data-interactive
            type="button"
            title="Reopen the wiki"
            onClick={onOpenWiki}
          >
            Wiki
          </button>
        )}
        <div
          className="resize-corner"
          data-interactive
          title="Drag to resize"
          onPointerDown={startResize}
        />
      </div>
    </div>
  );
}
