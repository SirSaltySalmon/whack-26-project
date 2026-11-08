import { spawn } from "node:child_process";
import type { LauncherConfig } from "../lib/launcher.ts";
import type { MemoryAdminResult } from "../lib/protocol.generated.ts";
import { killTree, pythonFor, repoRoot } from "./brainProcess.ts";

/** A separate local helper: no brain startup, game detection or model providers. */
export function manageMemory(
  config: LauncherConfig,
  request: unknown,
): Promise<MemoryAdminResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(pythonFor(config), ["-m", "brain.memory.admin"], {
      cwd: repoRoot(),
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
    });
    let output = "";
    let errors = "";
    const timer = setTimeout(() => {
      killTree(child);
      reject(new Error("Memory maintenance timed out"));
    }, 30000);
    child.stdout.on("data", (chunk: Buffer) => (output += chunk.toString()));
    child.stderr.on("data", (chunk: Buffer) => (errors += chunk.toString()));
    child.stdin.on("error", (error) => reject(error));
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        reject(
          new Error(
            errors.trim().split(/\r?\n/).pop() || "Memory maintenance failed",
          ),
        );
        return;
      }
      try {
        resolve(JSON.parse(output) as MemoryAdminResult);
      } catch {
        reject(new Error("Could not read the memory maintenance result"));
      }
    });
    child.stdin.end(JSON.stringify(request));
  });
}
