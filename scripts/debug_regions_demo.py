"""Draws fixed HUD-region boxes on the overlay, to prove its debug view works without the learner.

Usage: .\\run.cmd scripts\\debug_regions_demo.py   or, with the overlay already running:
       python scripts/debug_regions_demo.py

No game, mic, learner or API keys. It stands in for the brain on the same socket and sends what
--debug-regions sends: five labelled boxes, twice a second, each showing a reading that ticks and a
status that cycles ok, masked, unreadable every few seconds. If they appear and change, the overlay
side works, and a missing box in a real run is the learner's doing. Ctrl+C stops it.
"""

import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from brain.config import WS_HOST, Settings  # noqa: E402
from brain.events import EventBus  # noqa: E402
from brain.server import OverlayLink, create_app  # noqa: E402
from scripts.overlay_demo import offer_settings  # noqa: E402
from shared.protocol.messages import DebugRegion, DebugRegions, Rect  # noqa: E402

log = logging.getLogger("debug_regions_demo")

# Like the brain while debugging: the overlay hides the view 3 s after the last message.
SEND_EVERY_S = 0.5
STATUS_EVERY_TICKS = 6  # Each status shows for 3 s
STATUSES = ("ok", "masked", "unreadable")
# In DIPs, inside 1280 x 720 so every box is on screen at 150% Windows scaling too.
BOXES = (
    ("top left", Rect(x=40, y=40, width=220, height=30)),
    ("top right", Rect(x=1020, y=40, width=220, height=30)),
    ("centre", Rect(x=530, y=330, width=220, height=60)),
    ("bottom left", Rect(x=40, y=650, width=220, height=30)),
    ("tall bar", Rect(x=1200, y=200, width=30, height=300)),
)


def regions_at(tick: int) -> DebugRegions:
    """What to draw on this tick: readings count up, statuses take turns across the boxes."""
    regions = []
    for index, (name, rect) in enumerate(BOXES):
        status = STATUSES[(tick // STATUS_EVERY_TICKS + index) % len(STATUSES)]
        display = f"{(tick * 7 + index * 20) % 101}%" if status == "ok" else None
        regions.append(DebugRegion(name=name, rect=rect, status=status, display=display))
    return DebugRegions(regions=regions)


async def draw(link: OverlayLink) -> None:
    tick = 0
    while True:
        await link.send(regions_at(tick))
        if tick % STATUS_EVERY_TICKS == 0:
            log.info(
                "Drawing %d boxes (tick %d); connect the overlay to see them", len(BOXES), tick
            )
        tick += 1
        await asyncio.sleep(SEND_EVERY_S)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    link = OverlayLink(EventBus())
    settings = Settings()
    offer_settings(link, settings)
    config = uvicorn.Config(
        create_app(link), host=WS_HOST, port=settings.brain_port, log_level="warning"
    )
    log.info("Waiting for the overlay on ws://%s:%s/ws", WS_HOST, settings.brain_port)
    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(uvicorn.Server(config).serve())
        tasks.create_task(draw(link))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Stopped")
