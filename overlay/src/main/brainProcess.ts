import { type ChildProcess, spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { app } from "electron";
import type { DescribeResult, ProcessSnapshot } from "../lib/controlBridge.ts";
import {
  brainArgs,
  KEY_NAMES,
  toEnv,
  type KeyName,
  type LauncherConfig,
} from "../lib/launcher.ts";
import { logger } from "../lib/logger.ts";
import type {
  BrainDescription,
  VoiceOption,
} from "../lib/protocol.generated.ts";

const MAX_LOG_LINES = 2000;
const LOG_FLUSH_MS = 100;
const STOP_GRACE_MS = 5000;
const DESCRIBE_TIMEOUT_MS = 20000;
const READY_LINE = "Brain listening on";
const BRAIN_PORT = process.env["VITE_BRAIN_PORT"] ?? "8765";
// Colour codes would show up as junk in the window.
const ANSI = /\x1b\[[0-9;]*m/g;

/** In development the app path is overlay/, so the repo is one level up. */
export function repoRoot(): string {
  return resolve(app.getAppPath(), "..");
}

export function pythonFor(config: LauncherConfig): string {
  if (config.pythonPath.trim()) return config.pythonPath.trim();
  const venv =
    process.platform === "win32"
      ? join(repoRoot(), ".venv", "Scripts", "python.exe")
      : join(repoRoot(), ".venv", "bin", "python");
  return existsSync(venv) ? venv : "python";
}

/** Runs `python -m brain --describe`, with no keys added, so it reports what .env provides. */
export function describeBrain(config: LauncherConfig): Promise<DescribeResult> {
  return new Promise((done) => {
    let stdout = "";
    let stderr = "";
    const child = spawn(pythonFor(config), ["-m", "brain", "--describe"], {
      cwd: repoRoot(),
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
      windowsHide: true,
    });
    const timer = setTimeout(() => {
      child.kill();
      done({ ok: false, error: "The brain took too long to describe itself" });
    }, DESCRIBE_TIMEOUT_MS);
    child.stdout.on("data", (chunk: Buffer) => (stdout += chunk.toString()));
    child.stderr.on("data", (chunk: Buffer) => (stderr += chunk.toString()));
    child.on("error", (error) => {
      clearTimeout(timer);
      done({ ok: false, error: `Could not run Python: ${error.message}` });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      const line = stdout.trim().split(/\r?\n/).pop() ?? "";
      try {
        done({ ok: true, description: JSON.parse(line) as BrainDescription });
      } catch {
        const reason =
          stderr.trim().split(/\r?\n/).pop() ?? `exit code ${code}`;
        done({ ok: false, error: `Describe failed: ${reason}` });
      }
    });
  });
}

/** Ends the whole tree: on Windows a venv's python.exe starts the real interpreter as a child. */
export function killTree(child: ChildProcess): void {
  if (child.pid === undefined) return;
  if (process.platform === "win32") {
    spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], {
      windowsHide: true,
    }).on("error", (error) => logger.error("taskkill failed", error));
  } else {
    child.kill("SIGKILL");
  }
}

/** Asks the brain to stop cleanly over /control, so memory closes the session. */
function requestShutdown(): void {
  try {
    const socket = new WebSocket(`ws://127.0.0.1:${BRAIN_PORT}/control`);
    socket.onopen = () => {
      socket.send(JSON.stringify({ type: "control.shutdown" }));
      socket.close();
    };
    socket.onerror = () => logger.warn("Brain didn't answer the stop request");
  } catch (error) {
    logger.warn("Could not ask the brain to stop", error);
  }
}

export class BrainProcess {
  private child: ChildProcess | null = null;
  private snapshot: ProcessSnapshot = {
    state: "stopped",
    pid: null,
    exitCode: null,
    startedAt: null,
    startedWithKeys: [],
  };
  private readonly lines: string[] = [];
  private pending: string[] = [];
  private flushTimer: ReturnType<typeof setTimeout> | null = null;
  private stopping: Promise<ProcessSnapshot> | null = null;

  onChange: (snapshot: ProcessSnapshot) => void = () => undefined;
  onLines: (lines: string[]) => void = () => undefined;

  get current(): ProcessSnapshot {
    return this.snapshot;
  }

  get logs(): string[] {
    return [...this.lines];
  }

  get alive(): boolean {
    return this.child !== null;
  }

  start(
    config: LauncherConfig,
    keys: Partial<Record<KeyName, string>>,
    envVoices: readonly VoiceOption[],
  ): ProcessSnapshot {
    if (this.child) return this.snapshot;
    const python = pythonFor(config);
    const args = brainArgs(config);
    this.log(`> ${python} ${args.join(" ")}`);
    const child = spawn(python, args, {
      cwd: repoRoot(),
      env: { ...process.env, ...toEnv(config, keys, envVoices) },
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    this.child = child;
    this.update({
      state: "starting",
      pid: child.pid ?? null,
      exitCode: null,
      startedAt: Date.now(),
      startedWithKeys: KEY_NAMES.filter((name) => keys[name]),
    });
    this.readLines(child.stdout);
    this.readLines(child.stderr);
    child.on("error", (error) => {
      this.log(`Could not start the brain: ${error.message}`);
      this.ended(child, null);
    });
    child.on("exit", (code) => this.ended(child, code));
    return this.snapshot;
  }

  stop(): Promise<ProcessSnapshot> {
    const child = this.child;
    if (!child) return Promise.resolve(this.snapshot);
    this.stopping ??= new Promise((done) => {
      this.update({ ...this.snapshot, state: "stopping" });
      requestShutdown();
      const timer = setTimeout(() => {
        this.log("The brain didn't stop in time; ending it");
        killTree(child);
      }, STOP_GRACE_MS);
      child.once("exit", () => {
        clearTimeout(timer);
        done(this.snapshot);
      });
    });
    return this.stopping;
  }

  type(text: string): void {
    const line = text
      .replace(/[\r\n]+/g, " ")
      .trim()
      .slice(0, 500);
    if (!line || !this.child?.stdin?.writable) return;
    this.log(`you> ${line}`);
    this.child.stdin.write(`${line}\n`);
  }

  private ended(child: ChildProcess, code: number | null): void {
    if (this.child !== child) return;
    const clean = this.stopping !== null || code === 0;
    this.child = null;
    this.stopping = null;
    this.log(`Brain exited${code === null ? "" : ` with code ${code}`}`);
    this.update({
      ...this.snapshot,
      state: clean ? "stopped" : "crashed",
      pid: null,
      exitCode: code,
    });
  }

  private readLines(stream: NodeJS.ReadableStream | null): void {
    if (!stream) return;
    let partial = "";
    stream.on("data", (chunk: Buffer) => {
      const parts = (partial + chunk.toString()).split(/\r?\n/);
      partial = parts.pop() ?? "";
      for (const part of parts) this.log(part);
    });
  }

  private log(raw: string): void {
    const line = raw.replace(ANSI, "");
    if (!line.trim()) return;
    if (this.snapshot.state === "starting" && line.includes(READY_LINE)) {
      this.update({ ...this.snapshot, state: "running" });
    }
    this.lines.push(line);
    if (this.lines.length > MAX_LOG_LINES) this.lines.shift();
    this.pending.push(line);
    // Batched, because a chatty brain would otherwise send hundreds of IPC messages a second.
    this.flushTimer ??= setTimeout(() => {
      this.flushTimer = null;
      const batch = this.pending;
      this.pending = [];
      this.onLines(batch);
    }, LOG_FLUSH_MS);
  }

  private update(snapshot: ProcessSnapshot): void {
    this.snapshot = snapshot;
    this.onChange(snapshot);
  }
}
