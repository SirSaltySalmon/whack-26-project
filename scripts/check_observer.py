"""Watches the live game with the vision model and prints what it reports and what gets confirmed.

Usage: python scripts/check_observer.py [--process Terraria] [--seconds 30]
Start it, then click into the game and keep it in front. It costs about 3 cents a minute, and frames
go to Anthropic, so turn off the Steam overlay and keep anything private off the game window.
"""

import argparse
import asyncio
import logging
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brain.capture.loop import CaptureLoop  # noqa: E402
from brain.capture.ring_buffer import RingBuffer  # noqa: E402
from brain.capture.source import default_live_source  # noqa: E402
from brain.capture.window import create_game_window  # noqa: E402
from brain.config import Settings  # noqa: E402
from brain.events import EventBus, GameEvent  # noqa: E402
from brain.llm.factory import LLMFactory  # noqa: E402
from brain.perception.focus import Focus, FocusIntervals  # noqa: E402
from brain.perception.observation import Observation  # noqa: E402
from brain.perception.observer import Observer  # noqa: E402
from brain.perception.tracker import ObservationTracker  # noqa: E402
from shared.protocol.messages import Rect  # noqa: E402


@dataclass
class NoOverlay:
    rects: tuple[Rect, ...] = ()
    display_scale: float = 1.0


async def main() -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--process", default=settings.game_process or "Terraria")
    parser.add_argument("--seconds", type=float, default=30)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    overlay = NoOverlay()
    bus = EventBus()
    events = bus.subscribe()
    buffer = RingBuffer(settings.capture_fps * settings.ring_buffer_seconds)
    capture = CaptureLoop(
        default_live_source(),
        buffer,
        overlay,
        settings.capture_fps,
        create_game_window(args.process),
    )
    ages: list[float] = []

    def show(observation: Observation, frame_ts: float) -> None:
        ages.append(time.monotonic() - frame_ts)
        threats = f" threats={observation.threats}" if observation.threats else ""
        print(
            f"[{ages[-1]:4.1f}s old] {observation.screen_type:9}"
            f" danger={observation.danger_level:6}"
            f" health={observation.health_raw} | {observation.summary}{threats}"
        )

    observer = Observer(
        buffer,
        overlay,
        LLMFactory(settings).observer(),
        bus,
        ObservationTracker(),
        Focus(
            FocusIntervals(
                settings.observer_interval_low_s,
                settings.observer_interval_medium_s,
                settings.observer_interval_high_s,
            ),
            settings.focus_hold_s,
        ),
        settings.ai_image_max_edge_px,
        settings.mask_padding_px,
        on_observation=show,
    )

    async def print_events() -> None:
        while True:
            event = await events.get()
            if isinstance(event, GameEvent):
                print(f"  >>> CONFIRMED {event.name} {event.data}")

    print(f"Watching '{args.process}' for {args.seconds:.0f}s. Keep the game in front.")
    tasks = [asyncio.create_task(work) for work in (capture.run(), observer.run(), print_events())]
    await asyncio.sleep(args.seconds)
    final = observer.live_state()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    print(f"\n{len(ages)} reports in {args.seconds:.0f}s")
    if ages:
        median, worst = statistics.median(ages), max(ages)
        print(f"Report age when it arrived: median {median:.2f}s, worst {worst:.2f}s")
    print("What the talker would see now:", final)
    return 0 if ages else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
