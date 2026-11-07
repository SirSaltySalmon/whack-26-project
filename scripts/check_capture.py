"""Checks live capture of the game window: rate, cost and what the frames actually show.

Usage: python scripts/check_capture.py [--process Terraria] [--seconds 30] [--fps 2]
Start the script, then click into the game and keep it in front. Sample images are saved under
sessions/, which is gitignored. Open one and check that it shows only the game.
"""

import argparse
import asyncio
import logging
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from brain.capture.loop import CaptureLoop  # noqa: E402
from brain.capture.ring_buffer import Frame, RingBuffer  # noqa: E402
from brain.capture.source import default_live_source  # noqa: E402
from brain.capture.window import GameWindow  # noqa: E402
from brain.config import Settings  # noqa: E402
from shared.protocol.messages import Rect  # noqa: E402

SAMPLES_SAVED = 3


@dataclass
class NoOverlay:
    rects: tuple[Rect, ...] = ()


async def watch(buffer: RingBuffer, seconds: float) -> list[Frame]:
    """Collects each new frame. Polling here avoids changing the loop just for this check."""
    seen: list[Frame] = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        latest = buffer.latest()
        if latest is not None and (not seen or latest.ts != seen[-1].ts):
            seen.append(latest)
        await asyncio.sleep(0.02)
    return seen


def report(frames: list[Frame], fps: int, seconds: float, cpu_seconds: float, out_dir: Path) -> int:
    print(f"\nCaptured {len(frames)} frames in {seconds:.0f}s")
    print(f"CPU: {cpu_seconds / seconds:.1%} of one core, including this script's own polling")
    if not frames:
        print("No frames. Was the game in front? The log above says why capture stopped.")
        return 1

    gaps = [later.ts - earlier.ts for earlier, later in zip(frames, frames[1:], strict=False)]
    region = frames[-1].region
    height, width = frames[-1].image.shape[:2]
    megabytes = frames[-1].image.nbytes / 2**20
    print(f"Frame size: {width}x{height}, {megabytes:.1f} MB each, region {region}")
    if gaps:
        print(
            f"Interval: median {statistics.median(gaps):.3f}s, longest {max(gaps):.3f}s "
            f"(target {1 / fps:.3f}s)"
        )

    out_dir.mkdir(parents=True)
    step = max(1, len(frames) // SAMPLES_SAVED)
    for index, frame in enumerate(frames[::step][:SAMPLES_SAVED]):
        cv2.imwrite(str(out_dir / f"sample-{index}.jpg"), frame.image)
    print(f"Samples saved to {out_dir}")
    return 0


async def main() -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--process", default=settings.game_process or "Terraria")
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--fps", type=int, default=settings.capture_fps)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    buffer = RingBuffer(args.fps * settings.ring_buffer_seconds)
    capture = CaptureLoop(
        default_live_source(), buffer, NoOverlay(), args.fps, GameWindow(args.process)
    )
    print(f"Capturing '{args.process}' for {args.seconds:.0f}s. Keep the game in front.")

    cpu_started = time.process_time()
    task = asyncio.create_task(capture.run())
    frames = await watch(buffer, args.seconds)
    cpu_seconds = time.process_time() - cpu_started
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    out_dir = settings.sessions_dir / f"capture-check-{datetime.now():%Y%m%d-%H%M%S}"
    return report(frames, args.fps, args.seconds, cpu_seconds, out_dir)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
