import { logger } from "../../lib/logger.ts";
import { MouseCapture } from "../logic/mouseCapture.ts";

/** Marks an element that catches clicks. Everything else lets them through to the game. */
export const INTERACTIVE_SELECTOR = "[data-interactive]";

const GESTURING_CLASS = "gesturing";

export const mouseCapture = new MouseCapture((capture) => {
  logger.debug(`Mouse capture ${capture ? "on" : "off"}`);
  window.overlay.setMouseCapture(capture);
});

export function isOverInteractive(x: number, y: number): boolean {
  return document.elementFromPoint(x, y)?.closest(INTERACTIVE_SELECTOR) != null;
}

/** The class stops an embedded page from swallowing the drag. See styles.css. */
export function beginGesture(): void {
  document.body.classList.add(GESTURING_CLASS);
  mouseCapture.beginGesture();
}

export function endGesture(x: number, y: number): void {
  document.body.classList.remove(GESTURING_CLASS);
  mouseCapture.endGesture(isOverInteractive(x, y));
}
