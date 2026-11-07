import { useEffect } from "react";
import { isOverInteractive, mouseCapture } from "../lib/input.ts";

/** Runs on forwarded mouse moves, which keep arriving while the window lets clicks through. */
export function useClickThrough(): void {
  useEffect(() => {
    const onMove = (event: MouseEvent): void => {
      if (!mouseCapture.isGesturing) {
        mouseCapture.hover(isOverInteractive(event.clientX, event.clientY));
      }
    };
    window.addEventListener("mousemove", onMove);
    // Moves over an embedded page go to the page, so only this fires when the cursor enters one.
    window.addEventListener("mouseover", onMove);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseover", onMove);
    };
  }, []);
}
