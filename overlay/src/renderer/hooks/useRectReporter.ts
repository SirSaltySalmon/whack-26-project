import { useEffect } from "react";
import type { ElementRect } from "../../lib/protocol.generated.ts";
import type { BrainSocket } from "../lib/brainSocket.ts";
import { sameRects, visibleRects } from "../logic/rects.ts";

const REPORT_INTERVAL_MS = 100; // Capture runs at about 5 fps, so this reaches every frame in time.

function collect(): ElementRect[] {
  const elements = document.querySelectorAll<HTMLElement>("[data-rect-id]");
  return visibleRects(
    Array.from(elements, (element) => {
      const { x, y, width, height } = element.getBoundingClientRect();
      return {
        element_id: element.dataset["rectId"] ?? "",
        rect: { x, y, width, height },
      };
    }),
  );
}

/**
 * Polls instead of hooking each element, so one path covers drags, Motion animations, opening and
 * closing, and nothing can forget to report. `generation` changes on each connection, because the
 * brain forgets rects when the socket drops.
 */
export function useRectReporter(
  socket: BrainSocket | null,
  generation: number,
): void {
  useEffect(() => {
    if (!socket || generation === 0) return;
    let last: ElementRect[] | null = null;
    const report = (): void => {
      const rects = collect();
      if (last === null || !sameRects(last, rects)) {
        last = rects;
        socket.send({ type: "overlay.rects", rects });
      }
    };
    report();
    const timer = setInterval(report, REPORT_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [socket, generation]);
}
