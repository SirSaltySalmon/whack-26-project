import asyncio
import logging
from collections.abc import Callable, Collection
from pathlib import Path

import cv2
import numpy as np
import pytest

from brain.capture.ring_buffer import RingBuffer
from brain.events import (
    Event,
    EventBus,
    GameEvent,
    PlayerSpeech,
    PlayerStartedSpeaking,
    SettingsChanged,
)
from brain.perception.closeup import make_closeup
from brain.perception.coords import CropRegion
from brain.perception.masking import mask_overlay
from brain.replay.format import EVENTS, FRAMES_DIR, MANIFEST, PARTNER_SAID
from brain.replay.source import ReplayLoop
from brain.tests.fakes import FakeOverlay, drain
from brain.tests.replay_rig import RigFrame, RigSession, event, message, solid_image, write_session
from shared.protocol.messages import Rect

START = 100.0


class FakeTime:
    """A clock that only moves when the replay sleeps, so pacing is exact and instant."""

    def __init__(self) -> None:
        self.now = START
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        await asyncio.sleep(0)


class TimedBus(EventBus):
    def __init__(self, time: FakeTime) -> None:
        super().__init__()
        self.times: list[float] = []
        self._time = time

    def publish(self, event: Event) -> None:
        self.times.append(self._time.now)
        super().publish(event)


async def replay(
    session: Path,
    *,
    speed: float = 1.0,
    time: FakeTime | None = None,
    clock: Callable[[], float] | None = None,
    suppressed: Callable[[], Collection[str]] = frozenset,
    bus: EventBus | None = None,
) -> tuple[RingBuffer, list[Event], FakeOverlay]:
    time = time or FakeTime()
    buffer, bus, link = RingBuffer(16), bus or EventBus(), FakeOverlay()
    queue = bus.subscribe()
    clock = clock or time.clock
    loop = ReplayLoop(session, buffer, bus, link, speed, clock, time.sleep, suppressed)
    await loop.run()
    assert loop.finished.is_set()
    return buffer, drain(queue), link


def mean_fill(image: np.ndarray) -> float:
    return float(image.mean())


async def test_frames_reach_the_buffer_with_their_region_and_rects(tmp_path: Path) -> None:
    region = CropRegion(10, 20, 64, 36)
    rects = (Rect(x=1, y=2, width=3, height=4),)
    session = RigSession(
        frames=[RigFrame(0.0, solid_image(40)), RigFrame(0.2, solid_image(200), region, rects)]
    )
    buffer, _, _ = await replay(write_session(tmp_path, session))

    assert len(buffer) == 2
    first, second = buffer.nearest(START), buffer.latest()
    assert first is not None and second is not None
    assert abs(mean_fill(first.image) - 40) < 2 and abs(mean_fill(second.image) - 200) < 2
    assert (first.region, first.overlay_rects) == (None, ())
    assert (second.region, second.overlay_rects) == (region, rects)
    assert second.ts == pytest.approx(START + 0.2)


async def test_events_arrive_in_order_without_reader_events_or_partner_lines(
    tmp_path: Path,
) -> None:
    session = RigSession(
        events=[
            event(2.0, "PlayerSpeech", transcript="what's that?"),
            event(0.5, "PlayerStartedSpeaking"),
            event(1.0, "GameEvent", name="danger_started", data={"level": "high"}),
            event(1.5, "GameEvent", name="health_low", source="reader"),
            event(1.8, PARTNER_SAID, text="Careful."),
            event(1.9, "Tick"),
        ]
    )
    _, events, _ = await replay(write_session(tmp_path, session))

    assert [type(e) for e in events] == [PlayerStartedSpeaking, GameEvent, PlayerSpeech]
    game = events[1]
    assert isinstance(game, GameEvent)
    assert (game.name, game.data, game.source) == ("danger_started", {"level": "high"}, "replay")


async def test_suppressed_names_are_checked_when_each_event_is_due(tmp_path: Path) -> None:
    covered: set[str] = set()

    class ReadersTakeOver(FakeTime):
        async def sleep(self, seconds: float) -> None:
            await super().sleep(seconds)
            if self.now - START >= 2.0:
                covered.add("health_low")

    session = RigSession(
        events=[
            event(1.0, "GameEvent", name="health_low", data={"n": 1}),
            event(3.0, "GameEvent", name="health_low", data={"n": 2}),
            event(3.5, "GameEvent", name="item_found"),
        ]
    )
    directory = write_session(tmp_path, session)
    _, events, _ = await replay(directory, time=ReadersTakeOver(), suppressed=lambda: covered)

    assert [(e.name, e.data) for e in events if isinstance(e, GameEvent)] == [
        ("health_low", {"n": 1}),
        ("item_found", {}),
    ]


async def test_only_pointer_and_card_messages_are_sent_again(tmp_path: Path) -> None:
    session = RigSession(
        messages=[
            message(0.1, type="subtitle.chunk", utterance_id="u1", text="Hi", final=True),
            message(0.2, type="pointer.fly", x=10, y=20, label="Slime", ttl_ms=1500),
            message(0.3, type="toast.memory", text="Noted", source="player"),
            message(0.4, type="card.show", card_id="c1", title="Slime", body="Bouncy."),
            message(0.5, type="card.update", card_id="c1", body="Very bouncy."),
            message(0.6, type="question.ask", question_id="q1", text="Is that your base?"),
            message(0.7, type="pointer.fly", y=20),  # Invalid: no x.
            message(0.8, type="card.close", card_id="c1"),
            message(0.9, type="pointer.hide"),
            message(1.0, type="settings.state", settings={}),
        ]
    )
    _, _, link = await replay(write_session(tmp_path, session))

    assert [m.type for m in link.sent] == [
        "pointer.fly",
        "card.show",
        "card.update",
        "card.close",
        "pointer.hide",
    ]


async def test_scale_and_settings_come_from_the_manifest(tmp_path: Path) -> None:
    settings = {
        "proactive": False,
        "personality": "snarky",
        "voice_id": "v2",
        "voice_style": "classic",
        "mic_enabled": True,
        "memory_search": "semantic",
    }
    session = RigSession(display_scale=1.5, settings=settings)
    _, _, link = await replay(write_session(tmp_path, session))

    assert (link.display_scale, link.pinned_display_scale) == (1.5, 1.5)
    assert link.settings.model_dump() == settings


async def test_invalid_manifest_settings_keep_the_current_ones(tmp_path: Path) -> None:
    session = RigSession(settings={"proactive": "now and then"})
    _, _, link = await replay(write_session(tmp_path, session))

    assert link.settings.proactive is True


async def test_a_replayed_settings_change_updates_the_link(tmp_path: Path) -> None:
    changed = {"proactive": True, "personality": "calm", "voice_id": None}
    session = RigSession(events=[event(1.0, "SettingsChanged", settings=changed)])
    _, events, link = await replay(write_session(tmp_path, session))

    assert link.settings.personality == "calm"
    assert [type(e) for e in events] == [SettingsChanged]


@pytest.mark.parametrize("broken", ["missing", "manifest"])
async def test_a_bad_session_finishes_without_raising(tmp_path: Path, broken: str) -> None:
    session = tmp_path / "nowhere"
    if broken == "manifest":
        session = write_session(tmp_path, RigSession(frames=[RigFrame(0.0, solid_image())]))
        (session / MANIFEST).write_text("{", encoding="utf-8")
    buffer, events, link = await replay(session)

    assert (len(buffer), events, link.sent, link.pinned_display_scale) == (0, [], [], None)


async def test_a_truncated_last_event_line_is_tolerated(tmp_path: Path) -> None:
    session = write_session(tmp_path, RigSession(events=[event(0.5, "PlayerStartedSpeaking")]))
    with (session / EVENTS).open("a", encoding="utf-8") as lines:
        lines.write('{"t": 1.0, "kind": "PlayerSpe')
    _, events, _ = await replay(session)

    assert [type(e) for e in events] == [PlayerStartedSpeaking]


async def test_an_incomplete_session_still_plays(tmp_path: Path) -> None:
    session = RigSession(frames=[RigFrame(0.0, solid_image())])
    buffer, _, _ = await replay(write_session(tmp_path, session, complete=False))

    assert len(buffer) == 1


async def test_unreadable_frames_are_skipped_with_one_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    frames = [RigFrame(t, solid_image(fill)) for t, fill in ((0.0, 10), (0.2, 20), (0.4, 30))]
    session = write_session(tmp_path, RigSession(frames=frames))
    (session / FRAMES_DIR / "000001.jpg").write_bytes(b"not a jpeg")
    (session / FRAMES_DIR / "000002.jpg").unlink()
    with caplog.at_level(logging.WARNING, logger="brain.replay.source"):
        buffer, _, _ = await replay(session)

    assert len(buffer) == 1
    latest = buffer.latest()
    assert latest is not None and abs(mean_fill(latest.image) - 30) < 2
    assert len([r for r in caplog.records if "unreadable" in r.getMessage()]) == 1


async def test_items_wait_for_their_time_at_the_given_speed(tmp_path: Path) -> None:
    time = FakeTime()
    bus = TimedBus(time)
    session = RigSession(
        frames=[RigFrame(0.0, solid_image()), RigFrame(1.0, solid_image())],
        events=[event(2.0, "PlayerStartedSpeaking")],
        messages=[message(3.0, type="pointer.hide")],
    )
    buffer, _, _ = await replay(write_session(tmp_path, session), speed=2.0, time=time, bus=bus)

    first, last = buffer.nearest(START), buffer.latest()
    assert first is not None and last is not None
    assert (first.ts, last.ts) == (START, START + 0.5)
    assert bus.times == [START + 1.0]
    assert time.now == START + 1.5  # The message at t=3 waited until 3 / 2 seconds in.


async def test_late_frames_are_dropped_rather_than_decoded(tmp_path: Path) -> None:
    times = iter([START])

    def clock() -> float:
        return next(times, START + 10.0)  # Already ten seconds behind after the start.

    frames = [RigFrame(t, solid_image(fill)) for t, fill in ((0.0, 10), (0.2, 20), (0.4, 30))]
    buffer, _, _ = await replay(write_session(tmp_path, RigSession(frames=frames)), clock=clock)

    assert len(buffer) == 1
    latest = buffer.latest()
    assert latest is not None and abs(mean_fill(latest.image) - 30) < 2


def test_speed_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ReplayLoop(tmp_path, RingBuffer(1), EventBus(), FakeOverlay(), speed=0)


async def test_masking_covers_the_recorded_rects_on_replayed_frames(tmp_path: Path) -> None:
    region = CropRegion(100, 50, 200, 120)
    # At 1.5 scale this is physical (150, 75) to (180, 90), so frame pixels (50, 25) to (80, 40).
    rect = Rect(x=100, y=50, width=20, height=10)
    session = RigSession(
        frames=[RigFrame(0.0, solid_image(200, width=200, height=120), region, (rect,))],
        display_scale=1.5,
    )
    buffer, _, link = await replay(write_session(tmp_path, session))
    frame = buffer.latest()
    assert frame is not None

    masked = mask_overlay(frame.image, frame.overlay_rects, link.display_scale, 0, frame.region)
    assert not masked[25:40, 50:80].any()
    assert masked[:25].min() > 190 and masked[40:].min() > 190

    closeup = make_closeup(frame, link.display_scale, 0, max_edge_px=200)
    image = cv2.imdecode(np.frombuffer(closeup.image, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None and closeup.region == region
    assert image[28:37, 53:77].max() < 40  # Inside the mask, away from JPEG edge ringing.
    assert image[:15].min() > 180 and image[55:].min() > 180
