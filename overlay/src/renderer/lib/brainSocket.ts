import type { Brain, Overlay } from "../../lib/protocol.generated.ts";
import { brainUrl, JsonSocket, type JsonSocketHandlers } from "./jsonSocket.ts";

export const PROTOCOL_VERSION = 1; // Keep equal to PROTOCOL_VERSION in shared/protocol/messages.py.

export type BrainSocketHandlers = JsonSocketHandlers<Brain>;

/** The overlay's link on /ws. */
export class BrainSocket extends JsonSocket<Brain, Overlay> {
  constructor(handlers: BrainSocketHandlers) {
    super(brainUrl("/ws"), handlers);
  }
}
