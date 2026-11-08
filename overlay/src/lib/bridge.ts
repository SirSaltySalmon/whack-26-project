import type { PageText } from "./pageText.ts";

/** The only things the renderer can ask the main process to do. Web pages never get this bridge. */
export interface OverlayBridge {
  setMouseCapture(capture: boolean): void;
  requestTyping(): void;
  /** Gives the keyboard back to the game, so the player keeps moving after typing a turn. */
  endTyping(): void;
  /** The wiki window's rendered text, or null if there's no page or the read failed. */
  readPage(): Promise<PageText | null>;
}

export const IPC_SET_MOUSE_CAPTURE = "overlay:set-mouse-capture";
export const IPC_REQUEST_TYPING = "overlay:request-typing";
export const IPC_END_TYPING = "overlay:end-typing";
export const IPC_READ_PAGE = "overlay:read-page";
