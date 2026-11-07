import type { ReactNode } from "react";
import { useFrameGesture } from "../hooks/useFrameGesture.ts";
import {
  moveFrame,
  resizeFrame,
  type Frame,
  type SizeLimits,
} from "../logic/layout.ts";

interface CardWindowProps {
  rectId: string;
  title: string;
  frame: Frame;
  limits: SizeLimits;
  zIndex: number;
  /** Hidden rather than unmounted, so a minimized page keeps its place. */
  hidden?: boolean;
  controls?: ReactNode;
  onFrame(frame: Frame): void;
  onFrameEnd?(frame: Frame): void;
  onRaise(): void;
  onMinimize?(): void;
  onClose(): void;
  children: ReactNode;
}

/** The frame shared by text cards and the wiki window: title bar, move, resize and close. */
export function CardWindow({
  rectId,
  title,
  frame,
  limits,
  zIndex,
  hidden = false,
  controls,
  onFrame,
  onFrameEnd,
  onRaise,
  onMinimize,
  onClose,
  children,
}: CardWindowProps) {
  const startMove = useFrameGesture({
    frame,
    change: moveFrame,
    onFrame,
    onEnd: onFrameEnd,
  });
  const startResize = useFrameGesture({
    frame,
    change: (start, dx, dy, viewport) =>
      resizeFrame(start, dx, dy, viewport, limits),
    onFrame,
    onEnd: onFrameEnd,
  });

  return (
    <section
      className={`card${hidden ? " card-hidden" : ""}`}
      data-interactive
      data-rect-id={hidden ? undefined : rectId}
      style={{
        left: frame.x,
        top: frame.y,
        width: frame.width,
        height: frame.height,
        zIndex,
      }}
      onPointerDownCapture={onRaise}
    >
      <header className="card-bar" onPointerDown={startMove}>
        {controls}
        <h2 className="card-title" title={title}>
          {title}
        </h2>
        {/* Buttons stop the press here, so clicking one doesn't also start a drag. */}
        <div
          className="card-buttons"
          onPointerDown={(event) => event.stopPropagation()}
        >
          {onMinimize && (
            <button
              type="button"
              title="Minimize"
              aria-label="Minimize"
              onClick={onMinimize}
            >
              –
            </button>
          )}
          <button
            type="button"
            title="Close"
            aria-label="Close"
            onClick={onClose}
          >
            ×
          </button>
        </div>
      </header>
      <div className="card-content">{children}</div>
      <div
        className="resize-corner"
        title="Drag to resize"
        onPointerDown={startResize}
      />
    </section>
  );
}
