import { useState } from "react";
import { logger } from "../../lib/logger.ts";
import type { State } from "../../lib/protocol.generated.ts";
import { useFrameGesture } from "../hooks/useFrameGesture.ts";
import { useHovered } from "../hooks/useHovered.ts";
import type { AvatarLook } from "../logic/avatars.ts";
import { CHAT_OFFLINE_HINT } from "../logic/chat.ts";
import {
  AVATAR_LIMITS,
  moveFrame,
  resizeFrame,
  type Frame,
} from "../logic/layout.ts";

/**
 * The plain circle, or a picture fitted inside the 3:4 frame with its transparent parts showing
 * the game. If a picture can't load, the circle stands in so the partner never disappears.
 */
function AvatarArt({ state, look }: { state: State; look: AvatarLook }) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  if (look.kind === "loading") return null;
  if (look.kind === "circle" || failedSrc === look.src) {
    return <div className="avatar-art" data-state={state} />;
  }
  const src = look.src;
  return (
    <img
      className="avatar-image"
      data-state={state}
      src={src}
      alt=""
      draggable={false}
      onError={() => {
        logger.warn("Avatar image failed to load; showing the placeholder");
        setFailedSrc(src);
      }}
    />
  );
}

interface AvatarProps {
  frame: Frame;
  state: State;
  look: AvatarLook;
  onFrame(frame: Frame): void;
  onFrameEnd(frame: Frame): void;
  /** Reopens the wiki window. Null when there's nothing to reopen. */
  onOpenWiki: (() => void) | null;
  onOpenSettings(): void;
  /** Opens the chat box. Null while the brain is away: the button stays, disabled, to say why. */
  onOpenChat: (() => void) | null;
}

/**
 * The body isn't marked interactive, so clicks on it reach the game even while the controls show:
 * the game aims with the mouse. Hover still works because the window forwards mouse moves.
 */
export function Avatar({
  frame,
  state,
  look,
  onFrame,
  onFrameEnd,
  onOpenWiki,
  onOpenSettings,
  onOpenChat,
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
      <AvatarArt state={state} look={look} />
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
        <button
          className="avatar-button avatar-chat"
          data-interactive
          type="button"
          title={onOpenChat ? "Type to your partner" : CHAT_OFFLINE_HINT}
          aria-label="Type to your partner"
          disabled={onOpenChat === null}
          onClick={onOpenChat ?? undefined}
        >
          ⌨
        </button>
        <button
          className="avatar-button avatar-settings"
          data-interactive
          type="button"
          title="Settings"
          aria-label="Settings"
          onClick={onOpenSettings}
        >
          ⚙
        </button>
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
