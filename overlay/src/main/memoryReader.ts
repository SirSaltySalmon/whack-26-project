import { type ChildProcess, spawn } from "node:child_process";
import { createInterface } from "node:readline";
import {
  MEMORY_REPLY,
  type MemoryAnswer,
  type MemoryReply,
  type MemoryRequest,
} from "../lib/controlBridge.ts";
import { logger } from "../lib/logger.ts";
import { RequestTracker } from "../renderer/control/logic/requests.ts";
import { killTree } from "./brainProcess.ts";

// The first answer includes Python starting, which can take a few seconds from a cold disk.
const ANSWER_TIMEOUT_MS = 15000;
// Stopped when unused, so a window that looked once doesn't leave Python running.
const IDLE_STOP_MS = 5 * 60 * 1000;
const STOP_GRACE_MS = 2000;

export interface ReaderLaunch {
  python: string;
  cwd: string;
}

const messageOf = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);

/**
 * Reads memory with the partner off: `python -m brain --memory`, one JSON line per request and
 * per reply. The brain opens the database read-only, so this can keep running beside a partner.
 */
export class MemoryReader {
  private child: ChildProcess | null = null;
  private readonly requests = new RequestTracker(ANSWER_TIMEOUT_MS);
  private idleTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly launch: () => ReaderLaunch;

  constructor(launch: () => ReaderLaunch) {
    this.launch = launch;
  }

  async ask(request: MemoryRequest): Promise<MemoryAnswer> {
    const child = this.running();
    const { id, reply } = this.requests.open(MEMORY_REPLY[request.type]);
    child.stdin?.write(`${JSON.stringify({ ...request, request_id: id })}\n`);
    this.restartIdleTimer();
    try {
      return { ok: true, reply: (await reply) as MemoryReply };
    } catch (error) {
      return { ok: false, error: messageOf(error) };
    }
  }

  /** Closing stdin ends the reader's loop; the kill is only for one that hangs. */
  stop(): void {
    const child = this.child;
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.idleTimer = null;
    if (!child) return;
    this.child = null;
    this.requests.failAll("The memory reader stopped");
    child.stdin?.end();
    const timer = setTimeout(() => killTree(child), STOP_GRACE_MS);
    child.once("exit", () => clearTimeout(timer));
  }

  private running(): ChildProcess {
    if (this.child) return this.child;
    const { python, cwd } = this.launch();
    logger.info("Starting the memory reader");
    const child = spawn(python, ["-m", "brain", "--memory"], {
      cwd,
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    this.child = child;
    const gone = (reason: string): void => {
      if (this.child !== child) return;
      this.child = null;
      this.requests.failAll(reason);
    };
    child.on("error", (error) => {
      logger.error("Memory reader failed", error);
      gone(`Could not run Python: ${error.message}`);
    });
    child.on("exit", (code) => gone(`The memory reader exited (${code})`));
    child.stdin?.on("error", (error) =>
      logger.warn("Memory reader input closed", error),
    );
    if (child.stdout) {
      createInterface({ input: child.stdout }).on("line", (line) =>
        this.settle(line),
      );
    }
    if (child.stderr) {
      // The brain's own log lines, such as which database it opened.
      createInterface({ input: child.stderr }).on("line", (line) => {
        if (line.trim()) logger.info(`memory reader: ${line}`);
      });
    }
    return child;
  }

  private settle(line: string): void {
    let reply: unknown;
    try {
      reply = JSON.parse(line);
    } catch {
      logger.warn(
        "Memory reader sent a line that isn't JSON",
        line.slice(0, 200),
      );
      return;
    }
    if (typeof reply !== "object" || reply === null) return;
    if (!this.requests.settle(reply)) {
      logger.warn("Memory reader reply matched no request", line.slice(0, 200));
    }
  }

  private restartIdleTimer(): void {
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.idleTimer = setTimeout(() => {
      if (this.requests.size === 0) this.stop();
      else this.restartIdleTimer();
    }, IDLE_STOP_MS);
  }
}
