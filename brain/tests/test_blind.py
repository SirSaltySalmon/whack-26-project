"""Blinding the partner: readers stop, the look tools refuse, and it stops worrying about danger.

The observer's side is in test_observer.py, and the tracker forgetting a fight in test_tracker.py.
"""

import asyncio
import time
from typing import Any

import pytest

from brain.agent.schemas import BLINDED
from brain.agent.tools import TurnContext
from brain.capture.ring_buffer import Frame, RingBuffer
from brain.danger_feed import forward_danger
from brain.director.rules import AskQuestion, DirectorState, decide
from brain.events import EventBus, GameEvent, OverlayConnected, SettingsChanged, Tick
from brain.memory.models import GameProfile
from brain.perception.reader_engine import ReaderEngine
from brain.tests.agent_rig import LOOK, rig
from brain.tests.fakes import FakeOverlay, drain, make_frame
from brain.tests.reader_fixtures import health_frame_image, health_profile
from shared.protocol.messages import BrainMessage, DangerState, Settings

BLIND = Settings(vision_enabled=False)
SEEING = Settings()


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [("look_closer", LOOK), ("look_back", {"question": "what hit me?"})],
)
async def test_the_look_tools_refuse_without_calling_vision(
    tool: str, arguments: dict[str, str]
) -> None:
    now = time.monotonic()
    r = rig(*(make_frame(ts=now - age) for age in (6, 4, 2, 0)))
    r.overlay.settings = BLIND
    assert await r.run(tool, TurnContext(started_at=now), **arguments) == BLINDED
    assert r.vision.calls == []


async def test_blinded_readers_read_nothing_and_resume_when_vision_comes_back() -> None:
    vision_on = [True]
    now = [1000.0]
    buffer = RingBuffer(4)
    bus = EventBus()
    events = bus.subscribe()

    async def load() -> GameProfile:
        return GameProfile(game="Some Game", data=health_profile())

    engine = ReaderEngine(
        buffer,
        FakeOverlay(),
        bus,
        load,
        0,
        0.2,
        60.0,
        watching=lambda: vision_on[0],
        clock=lambda: now[0],
    )
    await engine.reload()

    async def show(fraction: float) -> list[Any]:
        now[0] += 0.25
        buffer.push(Frame(now[0], health_frame_image(fraction)))
        await engine.tick()
        return [event for event in drain(events) if isinstance(event, GameEvent)]

    await show(0.9)
    assert engine.live_state() == {"health": "90%"}
    vision_on[0] = False
    assert [await show(0.2) for _ in range(3)] == [[], [], []]
    assert engine.live_state() == {}

    vision_on[0] = True
    seen = [event for _ in range(2) for event in await show(0.2)]
    assert [event.name for event in seen] == ["health_low"]
    assert engine.live_state() == {"health": "20%"}


def test_blinding_ends_the_directors_worry_about_danger() -> None:
    state = DirectorState(question_quiet_s=0, question_gap_s=0, advice_gap_s=0)
    decide(OverlayConnected(display_scale=1.0, ts=0.0), state)
    decide(GameEvent("danger_started", {"level": "high"}, ts=1.0), state)
    # Settings that leave it seeing don't end a fight.
    decide(SettingsChanged(settings=SEEING, ts=2.0), state)
    assert state.in_danger
    assert decide(Tick(ts=3.0), state) == []

    decide(SettingsChanged(settings=BLIND, ts=4.0), state)
    assert not state.in_danger
    # Nothing holds a question back for a fight it can no longer see.
    assert decide(Tick(ts=5.0), state) == [AskQuestion()]


async def test_blinding_clears_the_danger_alert_once() -> None:
    bus = EventBus()
    sent: list[BrainMessage] = []

    async def send(message: BrainMessage) -> None:
        sent.append(message)

    task = asyncio.create_task(forward_danger(bus, send))
    await asyncio.sleep(0)
    for event in (
        GameEvent("danger_started", {"level": "high"}),
        SettingsChanged(settings=SEEING),
        SettingsChanged(settings=BLIND),
        SettingsChanged(settings=BLIND),
    ):
        bus.publish(event)
    await asyncio.sleep(0.05)
    task.cancel()

    assert sent == [DangerState(level="high"), DangerState(level="none")]
