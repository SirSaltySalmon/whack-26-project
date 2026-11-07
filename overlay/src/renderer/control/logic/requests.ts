/* Matches /control replies to the requests that asked for them. Pure, so it's tested directly. */

interface Pending {
  expect: string;
  resolve(reply: unknown): void;
  reject(error: Error): void;
  timer: ReturnType<typeof setTimeout>;
}

export interface Reply {
  type?: string;
  request_id?: string | null;
  message?: string;
}

export class RequestTracker {
  private readonly pending = new Map<string, Pending>();
  private readonly timeoutMs: number;
  private next = 0;

  constructor(timeoutMs = 5000) {
    this.timeoutMs = timeoutMs;
  }

  get size(): number {
    return this.pending.size;
  }

  /** A fresh request id, and the reply of type `expect` that answers it. */
  open(expect: string): { id: string; reply: Promise<unknown> } {
    this.next += 1;
    const id = `r${this.next}`;
    const reply = new Promise<unknown>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error("The brain didn't answer in time"));
      }, this.timeoutMs);
      this.pending.set(id, { expect, resolve, reject, timer });
    });
    return { id, reply };
  }

  /** Returns true if the message answered a request. */
  settle(message: Reply): boolean {
    const id = message.request_id;
    if (!id) return false;
    const waiting = this.pending.get(id);
    if (!waiting) return false;
    this.pending.delete(id);
    clearTimeout(waiting.timer);
    if (message.type === "control.error") {
      waiting.reject(new Error(message.message ?? "The brain couldn't answer"));
    } else if (message.type !== waiting.expect) {
      waiting.reject(
        new Error(`Expected ${waiting.expect}, got ${message.type}`),
      );
    } else {
      waiting.resolve(message);
    }
    return true;
  }

  /** On disconnect, so nothing waits for a reply that can't come. */
  failAll(reason: string): void {
    for (const waiting of this.pending.values()) {
      clearTimeout(waiting.timer);
      waiting.reject(new Error(reason));
    }
    this.pending.clear();
  }
}
