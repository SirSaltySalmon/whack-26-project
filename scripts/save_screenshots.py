"""Saves screenshots of the game for offline tests, spaced out so they show varied moments.

Usage: python scripts/save_screenshots.py [--count 20] [--every 5] [--process NAME]
Start it, then click into the game and play. It only captures while the game is in front, and it
waits if you switch away. Images go to sessions/, which is gitignored. Keep anything private out.
"""

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from brain.capture.loop import CaptureLoop  # noqa: E402
from brain.capture.ring_buffer import RingBuffer  # noqa: E402
from brain.capture.source import default_live_source  # noqa: E402
from brain.capture.window import create_game_window  # noqa: E402
from brain.config import Settings  # noqa: E402
from brain.game_setup import pick_game  # noqa: E402
from shared.protocol.messages import Rect  # noqa: E402


class NoOverlay:
    rects: tuple[Rect, ...] = ()


async def save_frames(buffer: RingBuffer, count: int, every: float, out_dir: Path) -> None:
    saved = 0
    last_ts = 0.0
    while saved < count:
        latest = buffer.latest()
        # A frame older than the interval means the game went out of front; wait for a new one.
        if latest is not None and latest.ts >= last_ts + every:
            saved += 1
            last_ts = latest.ts
            path = out_dir / f"frame-{saved:02d}.png"
            # PNG because compression artifacts would blur the small pixel font we're testing.
            await asyncio.to_thread(cv2.imwrite, str(path), latest.image)
            print(f"Saved {saved}/{count}: {path.name}")
        await asyncio.sleep(0.05)


async def main() -> None:
    settings = Settings()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--every", type=float, default=5.0, help="seconds between screenshots")
    parser.add_argument("--process", help="the game's process name; asks if unset")
    args = parser.parse_args()
    args.process = args.process or pick_game(settings)[0].game_process
    if not args.process:
        print("No game picked. Pass --process or set GAME_PROCESS.")
        return

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    out_dir = settings.sessions_dir / f"screenshots-{datetime.now():%Y%m%d-%H%M%S}"
    out_dir.mkdir(parents=True)

    fps = settings.capture_fps
    buffer = RingBuffer(fps * settings.ring_buffer_seconds)
    capture = CaptureLoop(
        default_live_source(), buffer, NoOverlay(), fps, create_game_window(args.process)
    )
    print(f"Saving {args.count} screenshots of '{args.process}', one every {args.every:g}s.")
    print("Click into the game now and keep playing.")

    started = time.monotonic()
    task = asyncio.create_task(capture.run())
    saver = asyncio.create_task(save_frames(buffer, args.count, args.every, out_dir))
    try:
        await saver
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    print(f"Done in {time.monotonic() - started:.0f}s. Screenshots are in {out_dir}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopped early. Anything already saved is still there.")
