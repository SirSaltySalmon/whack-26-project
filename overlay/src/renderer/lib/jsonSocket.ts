import { logger } from "../../lib/logger.ts";

const BRAIN_PORT = import.meta.env["VITE_BRAIN_PORT"] ?? "8765";
const MAX_RETRY_MS = 5000;

/** The brain's socket for a path such as "/ws" or "/control". */
export function brainUrl(path: string): string {
  return `ws://127.0.0.1:${BRAIN_PORT}${path}`;
}

export interface JsonSocketHandlers<In> {
  onOpen(): void;
  onMessage(message: In): void;
  onClose?(): void;
}

/** Keeps retrying, because the brain and the windows can start in either order. */
export class JsonSocket<In, Out extends { type?: string }> {
  private readonly url: string;
  private readonly handlers: JsonSocketHandlers<In>;
  private socket: WebSocket | null = null;
  private retryMs = 500;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;

  constructor(url: string, handlers: JsonSocketHandlers<In>) {
    this.url = url;
    this.handlers = handlers;
    this.connect();
  }

  get connected(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  send(message: Out): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message));
    } else {
      logger.debug(
        `Brain not connected; dropped ${message.type ?? "a message"}`,
      );
    }
  }

  close(): void {
    this.closed = true;
    if (this.retryTimer !== null) clearTimeout(this.retryTimer);
    this.socket?.close();
  }

  private connect(): void {
    const socket = new WebSocket(this.url);
    this.socket = socket;
    let opened = false;
    socket.onopen = () => {
      logger.info(`Connected to brain at ${this.url}`);
      opened = true;
      this.retryMs = 500;
      this.handlers.onOpen();
    };
    socket.onmessage = (event: MessageEvent<string>) =>
      this.receive(event.data);
    socket.onclose = () => {
      if (opened) this.handlers.onClose?.();
      if (this.closed) return;
      logger.debug(`Brain unavailable; retrying in ${this.retryMs} ms`);
      this.retryTimer = setTimeout(() => this.connect(), this.retryMs);
      this.retryMs = Math.min(this.retryMs * 2, MAX_RETRY_MS);
    };
  }

  private receive(text: string): void {
    try {
      this.handlers.onMessage(JSON.parse(text) as In);
    } catch (error) {
      // One bad message mustn't take a window down during a game.
      logger.error(
        `Could not handle brain message: ${text.slice(0, 200)}`,
        error,
      );
    }
  }
}
