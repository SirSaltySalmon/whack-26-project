import { useRef, type PointerEvent as ReactPointerEvent } from "react";
import { beginGesture, endGesture } from "../lib/input.ts";
import type { Frame, Size } from "../logic/layout.ts";

export type FrameChange = (
  frame: Frame,
  dx: number,
  dy: number,
  viewport: Size,
) => Frame;

interface GestureOptions {
  frame: Frame;
  /** Works out the new frame from the frame at the start of the drag and the drag distance. */
  change: FrameChange;
  onFrame(frame: Frame): void;
  onEnd?(frame: Frame): void;
}

/** One drag behavior for moving and resizing, used by the character and every card. */
export function useFrameGesture(options: GestureOptions) {
  const latest = useRef(options);
  latest.current = options;

  return (event: ReactPointerEvent<HTMLElement>): void => {
    if (event.button !== 0) return;
    event.preventDefault();

    const handle = event.currentTarget;
    const { pointerId, clientX: startX, clientY: startY } = event;
    const startFrame = latest.current.frame;
    let current = startFrame;

    // Capture keeps events coming to the handle even when the cursor outruns it.
    handle.setPointerCapture(pointerId);
    beginGesture();

    const onMove = (move: PointerEvent): void => {
      const viewport = { width: window.innerWidth, height: window.innerHeight };
      current = latest.current.change(
        startFrame,
        move.clientX - startX,
        move.clientY - startY,
        viewport,
      );
      latest.current.onFrame(current);
    };
    const onEnd = (end: PointerEvent): void => {
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onEnd);
      handle.removeEventListener("pointercancel", onEnd);
      handle.removeEventListener("lostpointercapture", onEnd);
      endGesture(end.clientX, end.clientY);
      latest.current.onEnd?.(current);
    };
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onEnd);
    handle.addEventListener("pointercancel", onEnd);
    // Capture can go without a release ever arriving. A drag left running would hold the mouse.
    handle.addEventListener("lostpointercapture", onEnd);
  };
}
