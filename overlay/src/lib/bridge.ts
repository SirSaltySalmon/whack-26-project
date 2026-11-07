/** The only things the renderer can ask the main process to do. Web pages never get this bridge. */
export interface OverlayBridge {
  setMouseCapture(capture: boolean): void;
  requestTyping(): void;
}

export const IPC_SET_MOUSE_CAPTURE = "overlay:set-mouse-capture";
export const IPC_REQUEST_TYPING = "overlay:request-typing";
