"""Drives the overlay without the rest of the brain: no game, no mic and no API keys.

Usage: python scripts/overlay_demo.py   then, in another terminal: npm --prefix overlay run dev

Uses the real brain server, so origin checks and message validation behave as they do in a real run.
"""

import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from brain.config import WS_HOST, Settings  # noqa: E402
from brain.events import Event, EventBus, OverlayConnected  # noqa: E402
from brain.server import OverlayLink, create_app  # noqa: E402
from shared.protocol.messages import (  # noqa: E402
    AvatarState,
    CardShow,
    PointerFly,
    Rect,
)

WIKI_URL = "https://terraria.wiki.gg/wiki/Eye_of_Cthulhu"
log = logging.getLogger("overlay_demo")


async def play(link: OverlayLink) -> None:
    await asyncio.sleep(1)
    await link.send(
        CardShow(
            card_id="wiki",
            title="Eye of Cthulhu",
            body="Offline fallback: the Eye of Cthulhu is an early boss.",
            source_url=WIKI_URL,
            page_url=WIKI_URL,
        )
    )
    await link.send(
        CardShow(card_id="note", title="Text card", body="Sanitized plain text in a card.")
    )
    while True:
        for state in ("listening", "talking", "reacting", "idle"):
            await link.send(AvatarState(state=state))
            await asyncio.sleep(1)
        await link.send(PointerFly(x=800, y=500, label="A point on screen", ttl_ms=3000))
        await asyncio.sleep(4)
        box = Rect(x=500, y=200, width=200, height=80)
        await link.send(PointerFly(x=600, y=240, label="Beside this box", target=box, ttl_ms=3000))
        await asyncio.sleep(5)


async def watch(bus: EventBus, link: OverlayLink) -> None:
    events: asyncio.Queue[Event] = bus.subscribe()
    player: asyncio.Task[None] | None = None
    while True:
        event = await events.get()
        log.info("Event: %s", event)
        if isinstance(event, OverlayConnected):
            if player:
                player.cancel()
            player = asyncio.create_task(play(link))


async def report_rects(link: OverlayLink) -> None:
    seen: tuple[Rect, ...] = ()
    while True:
        await asyncio.sleep(1)
        if link.rects != seen:
            seen = link.rects
            log.info("Masking %d overlay rects: %s", len(seen), seen)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    bus = EventBus()
    link = OverlayLink(bus)
    settings = Settings()
    config = uvicorn.Config(
        create_app(link), host=WS_HOST, port=settings.brain_port, log_level="warning"
    )
    log.info("Waiting for the overlay on ws://%s:%s/ws", WS_HOST, settings.brain_port)
    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(uvicorn.Server(config).serve())
        tasks.create_task(watch(bus, link))
        tasks.create_task(report_rects(link))


if __name__ == "__main__":
    asyncio.run(main())
