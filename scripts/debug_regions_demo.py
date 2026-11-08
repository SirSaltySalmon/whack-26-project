"""Draws fixed HUD-region boxes on the overlay, to prove its debug view works without the learner.

Usage: .\\run.cmd scripts\\debug_regions_demo.py   or, with the overlay already running:
       python scripts/debug_regions_demo.py

No game, mic, learner or API keys. It stands in for the brain on the same socket and sends what
--debug-regions sends: five labelled boxes, twice a second, each showing a reading that ticks and a
status that cycles ok, masked, unreadable every few seconds. It also sends what the observer and
tools would: two moving "noticed" boxes, and a look, a point and a look back in turn, each fading
on its own. The brain panel in the corner steps through a few made-up moments: hearing a
question, answering it with the wiki, and a danger bark then a cooldown. If they appear and
change, the overlay side works, and a missing box in a real run is the learner's or the
observer's doing. Ctrl+C stops it.
"""

import asyncio
import logging
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from brain.config import WS_HOST, Settings  # noqa: E402
from brain.events import EventBus  # noqa: E402
from brain.server import OverlayLink, create_app  # noqa: E402
from scripts.overlay_demo import offer_settings  # noqa: E402
from shared.protocol.messages import (  # noqa: E402
    DebugBrain,
    DebugLatency,
    DebugRegion,
    DebugRegions,
    DebugSighting,
    DebugSightings,
    Rect,
)

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

# Two things the observer "noticed", circling the middle of the screen at different speeds.
MOVERS = (("green slime", 0.25, 260, 160), ("demon eye", -0.4, 360, 220))
NOTICED_TTL_MS = 900  # A little past the send interval, so each box hands over to the next
TOOL_EVERY_TICKS = 8  # A tool's box every 4 s, taking turns
TOOL_TTL_MS = 3000
TOOLS = (
    DebugSighting(
        label="what's that up there?",
        rect=Rect(x=640, y=0, width=640, height=360),
        kind="look",
        ttl_ms=TOOL_TTL_MS,
    ),
    DebugSighting(
        label="the workbench",
        rect=Rect(x=300, y=520, width=70, height=40),
        kind="point",
        ttl_ms=TOOL_TTL_MS,
    ),
    DebugSighting(
        label="what hit me?",
        rect=Rect(x=0, y=0, width=1280, height=720),
        kind="look_back",
        ttl_ms=TOOL_TTL_MS,
    ),
)


def sightings_at(tick: int) -> DebugSightings:
    """The movers' boxes on every tick, plus the next tool's box every TOOL_EVERY_TICKS."""
    sightings = []
    for label, speed, radius_x, radius_y in MOVERS:
        angle = tick * speed
        x = 640 + radius_x * math.cos(angle) - 30
        y = 360 + radius_y * math.sin(angle) - 20
        rect = Rect(x=x, y=y, width=60, height=40)
        sightings.append(
            DebugSighting(label=label, rect=rect, kind="noticed", ttl_ms=NOTICED_TTL_MS)
        )
    if tick % TOOL_EVERY_TICKS == 0:
        sightings.append(TOOLS[tick // TOOL_EVERY_TICKS % len(TOOLS)])
    return DebugSightings(sightings=sightings)


def regions_at(tick: int) -> DebugRegions:
    """What to draw on this tick: readings count up, statuses take turns across the boxes."""
    regions = []
    for index, (name, rect) in enumerate(BOXES):
        status = STATUSES[(tick // STATUS_EVERY_TICKS + index) % len(STATUSES)]
        display = f"{(tick * 7 + index * 20) % 101}%" if status == "ok" else None
        regions.append(DebugRegion(name=name, rect=rect, status=status, display=display))
    return DebugRegions(regions=regions)


QUESTION = "what's the best boss to beat in the early game?"
# Made-up moments for the brain panel, each shown for SCENE_TICKS sends.
SCENE_TICKS = 8


def _timings(*pairs: tuple[str, int]) -> list[DebugLatency]:
    return [DebugLatency(label=label, ms=ms) for label, ms in pairs]


SCENES = [
    DebugBrain(hearing=QUESTION[:24], hearing_live=True, decision="listening", focus="low"),
    DebugBrain(
        hearing=QUESTION,
        mood="positive",
        mood_valence=0.5,
        decision="answering you",
        doing="wiki: Eye of Cthulhu",
        focus="low",
        latency=_timings(("turn, with tools", 2687), ("you stopped → voice", 1125)),
    ),
    DebugBrain(
        hearing=QUESTION,
        mood="frustrated",
        mood_valence=-0.5,
        decision="danger started: quick line",
        focus="high",
        latency=_timings(("frame → bark", 182), ("event → bark", 4), ("turn, with tools", 2687)),
    ),
    DebugBrain(
        hearing="that was close",
        mood="relieved",
        mood_valence=0.1,
        decision="health low: quiet, cooling down",
        focus="high",
        latency=_timings(("frame → bark", 182), ("event → bark", 4)),
    ),
]


def brain_at(tick: int) -> DebugBrain:
    return SCENES[(tick // SCENE_TICKS) % len(SCENES)]


async def draw(link: OverlayLink) -> None:
    tick = 0
    while True:
        await link.send(regions_at(tick))
        await link.send(sightings_at(tick))
        await link.send(brain_at(tick))
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
