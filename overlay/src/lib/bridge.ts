import type { PageText } from "./pageText.ts";

/** The only things the renderer can ask the main process to do. Web pages never get this bridge. */
export interface OverlayBridge {
  setMouseCapture(capture: boolean): void;
  requestTyping(): void;
  /** The wiki window's rendered text, or null if there's no page or the read failed. */
  readPage(): Promise<PageText | null>;
}

export const IPC_SET_MOUSE_CAPTURE = "overlay:set-mouse-capture";
export const IPC_REQUEST_TYPING = "overlay:request-typing";
export const IPC_READ_PAGE = "overlay:read-page";
