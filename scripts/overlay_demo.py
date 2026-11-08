"""Drives the overlay without the rest of the brain: no game, no mic and no API keys.

Usage: python scripts/overlay_demo.py   then, in another terminal: npm --prefix overlay run dev

Uses the real brain server, so origin checks and message validation behave as they do in a real run.

Each pass shows the avatar's states, the pointer, the danger alert rising and ending, the HUD
regions debug view, subtitles both ways,
a toast for each source and two spoken questions, so Stage 0 of docs/TEST_PLAN.md can be checked by
eye. Questions are only spoken, as in a real run: answering one in the overlay's text box moves on
straight away. The terminal logs what the overlay reports back, including typed turns and the
rectangles it wants masked.
"""

import asyncio
import logging
import sys
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from brain.config import WS_HOST, Settings  # noqa: E402
from brain.director.personalities import load_personalities  # noqa: E402
from brain.events import Event, EventBus, OverlayConnected, PlayerSpeech  # noqa: E402
from brain.server import OverlayLink, create_app  # noqa: E402
from shared.protocol import BrainMessage  # noqa: E402
from shared.protocol.messages import (  # noqa: E402
    AvatarState,
    CardShow,
    DangerState,
    DebugRegion,
    DebugRegions,
    MemoryToast,
    PointerFly,
    Rect,
    SubtitleChunk,
    VoiceOption,
)

WIKI_URL = "https://terraria.wiki.gg/wiki/Eye_of_Cthulhu"
log = logging.getLogger("overlay_demo")

# How long the overlay keeps each thing up, plus a moment, so nothing is cut off by what comes next
# and its rectangle can be seen leaving in the log. See useCompanionFeed.ts and Toasts.tsx.
SUBTITLE_HOLD_S = 3.0  # SUBTITLE_LINGER_MS is 2500
TOAST_HOLD_S = 4.5  # TOAST_MS is 4000
# The brain drops an unanswered question after question_answer_timeout_s, 20 s by default.
QUESTION_HOLD_S = 20.0
DEBUG_REGIONS_STALE_S = 3.0  # DEBUG_REGIONS_STALE_MS is 3000

WORD_GAP_S = 0.3
TOAST_GAP_S = 1.0
ANSWER_POLL_S = 0.25
# Like the brain while debugging: about twice a second, with the readings changing.
DEBUG_REGIONS_GAP_S = 0.5
DEBUG_HEALTH_READINGS = ("72/100", "68/100", "64/100", "60/100", "64/100", "68/100")

# Bare words and separate punctuation, because real word timings can arrive like this.
SPOKEN_WORDS = ("That", "looks", "like", "a", "tough", "fight", ",", "so", "stay", "sharp", ".")
WHOLE_LINE = "With no voice keys, the whole line arrives in one chunk."
TOASTS = (
    MemoryToast(text="Remembered: player class: summoner", source="player"),
    MemoryToast(text="Updated: base location: east of spawn", source="observed"),
    MemoryToast(text="Remembered: slime weakness: fire", source="wiki"),
)
QUESTIONS = ("What are you after next?", "What's that glowing thing for?")
# Nothing speaks in this demo, so picking one of these is harmless.
DEMO_VOICES = [
    VoiceOption(name="Demo voice A", id="demo-voice-a"),
    VoiceOption(name="Demo voice B", id="demo-voice-b"),
]

Sleep = Callable[[float], Awaitable[None]]


class Overlay(Protocol):
    async def send(self, message: BrainMessage) -> None: ...


def offer_settings(link: OverlayLink, settings: Settings) -> None:
    """Gives the settings panel something to show. The overlay gets this when it connects."""
    link.personalities = load_personalities().names
    link.voices = settings.voice_options or DEMO_VOICES


async def show_avatar_states(overlay: Overlay, sleep: Sleep) -> None:
    for state in ("listening", "talking", "reacting", "idle"):
        await overlay.send(AvatarState(state=state))
        await sleep(1)


async def show_pointer(overlay: Overlay, sleep: Sleep) -> None:
    await overlay.send(PointerFly(x=800, y=500, label="A point on screen", ttl_ms=3000))
    await sleep(4)
    box = Rect(x=500, y=200, width=200, height=80)
    await overlay.send(PointerFly(x=600, y=240, label="Beside this box", target=box, ttl_ms=3000))
    await sleep(5)


async def show_danger(overlay: Overlay, sleep: Sleep) -> None:
    log.info("Danger: rises, then ends")
    for level, hold in (("medium", 2), ("high", 5), ("none", 1)):
        await overlay.send(DangerState(level=level))
        await sleep(hold)


def debug_regions(health: str) -> DebugRegions:
    """Two made-up HUD boxes near the top, on screen even in a small window."""
    return DebugRegions(
        regions=[
            DebugRegion(
                name="health",
                rect=Rect(x=700, y=40, width=220, height=26),
                status="ok",
                display=health,
            ),
            DebugRegion(
                name="mana", rect=Rect(x=980, y=40, width=26, height=180), status="unreadable"
            ),
        ]
    )


async def show_debug_regions(overlay: Overlay, sleep: Sleep) -> None:
    log.info("Debug regions: health reads, mana doesn't")
    for health in DEBUG_HEALTH_READINGS:
        await overlay.send(debug_regions(health))
        await sleep(DEBUG_REGIONS_GAP_S)
    await overlay.send(DebugRegions(regions=[]))
    await sleep(1)


async def show_subtitles(overlay: Overlay, sleep: Sleep) -> None:
    """The two shapes the brain sends: real voice word by word, subtitles-only mode all at once."""
    log.info("Subtitles: word by word")
    utterance = uuid.uuid4().hex
    await overlay.send(AvatarState(state="talking"))
    for word in SPOKEN_WORDS:
        await overlay.send(SubtitleChunk(utterance_id=utterance, text=word))
        await sleep(WORD_GAP_S)
    await overlay.send(SubtitleChunk(utterance_id=utterance, text="", final=True))
    await overlay.send(AvatarState(state="idle"))
    await sleep(SUBTITLE_HOLD_S)

    log.info("Subtitles: one chunk")
    await overlay.send(AvatarState(state="talking"))
    await overlay.send(SubtitleChunk(utterance_id=uuid.uuid4().hex, text=WHOLE_LINE, final=True))
    await overlay.send(AvatarState(state="idle"))
    await sleep(SUBTITLE_HOLD_S)


async def show_toasts(overlay: Overlay, sleep: Sleep) -> None:
    log.info("Toasts: one for each source")
    for toast in TOASTS:
        await overlay.send(toast)
        await sleep(TOAST_GAP_S)
    await sleep(TOAST_HOLD_S)


async def ask(overlay: Overlay, question: str, answered: asyncio.Event, sleep: Sleep) -> None:
    """Says it, then holds until a typed reply arrives or the brain would have given up on it."""
    answered.clear()
    await overlay.send(AvatarState(state="talking"))
    await overlay.send(SubtitleChunk(utterance_id=uuid.uuid4().hex, text=question, final=True))
    await overlay.send(AvatarState(state="idle"))
    log.info("Question: %r. Waiting up to %.0f s for a typed reply", question, QUESTION_HOLD_S)
    waited = 0.0
    while waited < QUESTION_HOLD_S and not answered.is_set():
        await sleep(ANSWER_POLL_S)
        waited += ANSWER_POLL_S


async def one_pass(overlay: Overlay, answered: asyncio.Event, sleep: Sleep = asyncio.sleep) -> None:
    await show_avatar_states(overlay, sleep)
    await show_pointer(overlay, sleep)
    await show_danger(overlay, sleep)
    await show_debug_regions(overlay, sleep)
    await show_subtitles(overlay, sleep)
    await show_toasts(overlay, sleep)
    for question in QUESTIONS:
        await ask(overlay, question, answered, sleep)
        await sleep(1)


async def play(overlay: Overlay, answered: asyncio.Event, sleep: Sleep = asyncio.sleep) -> None:
    await sleep(1)
    await overlay.send(
        CardShow(
            card_id="wiki",
            title="Eye of Cthulhu",
            body="Offline fallback: the Eye of Cthulhu is an early boss.",
            source_url=WIKI_URL,
            page_url=WIKI_URL,
        )
    )
    await overlay.send(
        CardShow(card_id="note", title="Text card", body="Sanitized plain text in a card.")
    )
    while True:
        await one_pass(overlay, answered, sleep)


async def watch(bus: EventBus, overlay: Overlay, sleep: Sleep = asyncio.sleep) -> None:
    events: asyncio.Queue[Event] = bus.subscribe()
    answered = asyncio.Event()
    player: asyncio.Task[None] | None = None
    try:
        while True:
            event = await events.get()
            log.info("Event: %s", event)
            match event:
                case OverlayConnected():
                    if player:
                        player.cancel()
                    player = asyncio.create_task(play(overlay, answered, sleep))
                case PlayerSpeech():
                    # From the overlay's text box, which the real brain treats as speech.
                    answered.set()
    finally:
        if player:
            player.cancel()


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
    offer_settings(link, settings)
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
