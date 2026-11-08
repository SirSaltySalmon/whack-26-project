"""Starts the overlay and the brain from one terminal, and stops both when the brain stops.

Usage: python scripts/run_all.py --live --debug-regions --type --off observer,voice
Every argument goes to the brain unchanged. A .py path first runs that script in the brain's place,
such as `run.cmd scripts/debug_regions_demo.py`. On Windows, `run.cmd` in the repo root runs this
with the venv's Python, so nothing needs activating and the execution policy doesn't apply.

The brain runs in the foreground, so its log and `--type` input stay in this terminal. The
overlay runs in the background with its output prefixed, and doesn't get Ctrl+C: the brain stops
first, then this script ends the overlay's whole process tree.
"""

import logging
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import IO

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = sys.platform == "win32"

log = logging.getLogger("run_all")


def _forward(stream: IO[str]) -> None:
    # This must keep reading whatever happens: if it stopped, the pipe would fill and the
    # overlay would freeze on its next write. Vite prints characters such as ✓ that some
    # consoles can't show, so those are replaced rather than allowed to raise.
    encoding = sys.stdout.encoding or "utf-8"
    for line in stream:
        text = f"[overlay] {line}".encode(encoding, errors="replace").decode(encoding)
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except OSError:
            pass  # The terminal went away; keep draining the pipe anyway.


def start_overlay() -> subprocess.Popen[str]:
    env = dict(os.environ)
    # Set by some editor shells, and it makes Electron fail with "Cannot find module 'electron'".
    env.pop("ELECTRON_RUN_AS_NODE", None)
    npm = "npm.cmd" if WINDOWS else "npm"
    # Its own process group, so Ctrl+C reaches only the brain, and npm on Windows doesn't stop
    # to ask "Terminate batch job?".
    group: dict[str, object] = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if WINDOWS
        else {"start_new_session": True}
    )
    overlay = subprocess.Popen(
        [npm, "--prefix", "overlay", "run", "dev"],
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        **group,  # type: ignore[arg-type]
    )
    assert overlay.stdout is not None
    threading.Thread(target=_forward, args=(overlay.stdout,), daemon=True).start()
    return overlay


def stop_overlay(overlay: subprocess.Popen[str]) -> None:
    if overlay.poll() is not None:
        return
    log.info("Closing the overlay")
    if WINDOWS:
        # npm starts Vite and Electron as children, and only /T ends them too.
        subprocess.run(
            ["taskkill", "/PID", str(overlay.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        os.killpg(overlay.pid, signal.SIGTERM)
    try:
        overlay.wait(timeout=10)
    except subprocess.TimeoutExpired:
        log.warning("The overlay didn't close; end it from Task Manager")


def brain_command(args: list[str]) -> list[str]:
    """`run.cmd scripts/x.py ...` runs that script in the brain's place, such as a demo."""
    if args and args[0].endswith(".py"):
        return args
    return ["-m", "brain", *args]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[run_all] %(message)s")
    overlay = start_overlay()
    log.info("Overlay starting (pid %s); brain starting in this terminal", overlay.pid)
    brain = subprocess.Popen([sys.executable, *brain_command(sys.argv[1:])], cwd=ROOT)
    interrupts = 0
    try:
        while True:
            try:
                return brain.wait()
            except KeyboardInterrupt:
                # The brain got the same Ctrl+C and is closing memory; a second one won't wait.
                interrupts += 1
                if interrupts >= 2:
                    log.warning("Ending the brain without waiting")
                    brain.kill()
    finally:
        stop_overlay(overlay)


if __name__ == "__main__":
    sys.exit(main())
