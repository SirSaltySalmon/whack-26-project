import { logger } from "../../lib/logger.ts";
import type { Brain, Overlay } from "../../lib/protocol.generated.ts";

export const PROTOCOL_VERSION = 1; // Keep equal to PROTOCOL_VERSION in shared/protocol/messages.py.

const BRAIN_PORT = import.meta.env["VITE_BRAIN_PORT"] ?? "8765";
const BRAIN_URL = `ws://127.0.0.1:${BRAIN_PORT}/ws`;
const MAX_RETRY_MS = 5000;

export interface BrainSocketHandlers {
  onOpen(): void;
  onMessage(message: Brain): void;
}

/** Keeps retrying, because the brain and the overlay can start in either order. */
export class BrainSocket {
  private readonly handlers: BrainSocketHandlers;
  private socket: WebSocket | null = null;
  private retryMs = 500;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;

  constructor(handlers: BrainSocketHandlers) {
    this.handlers = handlers;
    this.connect();
  }

  get connected(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  send(message: Overlay): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message));
    } else {
      logger.debug(`Brain not connected; dropped ${message.type}`);
    }
  }

  close(): void {
    this.closed = true;
    if (this.retryTimer !== null) clearTimeout(this.retryTimer);
    this.socket?.close();
  }

  private connect(): void {
    const socket = new WebSocket(BRAIN_URL);
    this.socket = socket;
    socket.onopen = () => {
      logger.info(`Connected to brain at ${BRAIN_URL}`);
      this.retryMs = 500;
      this.handlers.onOpen();
    };
    socket.onmessage = (event: MessageEvent<string>) =>
      this.receive(event.data);
    socket.onclose = () => {
      if (this.closed) return;
      logger.debug(`Brain unavailable; retrying in ${this.retryMs} ms`);
      this.retryTimer = setTimeout(() => this.connect(), this.retryMs);
      this.retryMs = Math.min(this.retryMs * 2, MAX_RETRY_MS);
    };
  }

  private receive(text: string): void {
    try {
      this.handlers.onMessage(JSON.parse(text) as Brain);
    } catch (error) {
      // One bad message mustn't take the overlay down during a game.
      logger.error(
        `Could not handle brain message: ${text.slice(0, 200)}`,
        error,
      );
    }
  }
}
