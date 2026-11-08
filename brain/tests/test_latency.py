"""WP9: reactions are timed from the frame that showed them, not from when the event was published.

The observer publishes seconds after the frame, so timing from the event would hide the slow part.
"""

import time
from pathlib import Path

import pytest

from brain.director.rules import DirectorState, PlayBark, ReactToEvent, decide
from brain.events import EventBus, GameEvent
from brain.latency import STALE_AFTER_S, FirstAudio, Origin, log_frame_latency
from brain.perception.tracker import ObservationTracker
from brain.replay.format import event_record
from brain.tests.director_rig import Rig
from brain.tests.fakes import FakeBarkSynth, FakeTextLLM
from brain.tests.test_director_lines import BARK_BOOK
from brain.tests.test_observer import FakeVision, observer, report
from brain.tests.test_tracker import fight, frame
from brain.voice.barks import BarkBank

ORIGIN = Origin("danger_started", "observer", frame_ts=10.0, event_ts=12.4)


class Clock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def info(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level("INFO")
    return caplog


def test_only_an_event_with_a_frame_time_has_an_origin() -> None:
    assert Origin.of(GameEvent("danger_started")) is None
    event = GameEvent("health_low", source="reader", frame_ts=4.0, ts=4.5)
    assert Origin.of(event) == Origin("health_low", "reader", 4.0, 4.5)


def test_the_log_line_splits_noticing_from_speaking(info: pytest.LogCaptureFixture) -> None:
    log_frame_latency("first audio", ORIGIN, 12.95)
    # The report script and the Control Center's Latency tab parse exactly this.
    assert (
        "Latency: frame to first audio 2950 ms "
        "(danger_started from observer: noticed in 2400, spoke in 550)"
    ) in info.text


def test_a_queued_reaction_is_timed_once_when_its_audio_starts(
    info: pytest.LogCaptureFixture,
) -> None:
    clock = Clock(12.5)
    timer = FirstAudio(clock)
    timer.queued(ORIGIN, speaking=False)
    clock.now = 12.95
    timer.started()
    assert "frame to first audio 2950 ms" in info.text
    info.clear()
    timer.started()
    assert "Latency" not in info.text


def test_a_line_queued_behind_speech_is_not_timed(info: pytest.LogCaptureFixture) -> None:
    timer = FirstAudio(Clock(12.5))
    timer.queued(ORIGIN, speaking=True)
    timer.started()
    assert "Latency" not in info.text


def test_the_players_turn_drops_a_reaction_that_never_played(
    info: pytest.LogCaptureFixture,
) -> None:
    timer = FirstAudio(Clock(12.5))
    timer.queued(ORIGIN, speaking=False)
    timer.turn_started()
    timer.started()
    assert "Latency" not in info.text


def test_audio_long_after_queuing_is_not_credited_to_the_reaction(
    info: pytest.LogCaptureFixture,
) -> None:
    clock = Clock(12.5)
    timer = FirstAudio(clock)
    timer.queued(ORIGIN, speaking=False)
    clock.now += STALE_AFTER_S + 1
    timer.started()
    assert "Latency" not in info.text


def test_end_of_turn_timing_still_works(info: pytest.LogCaptureFixture) -> None:
    clock = Clock(1.0)
    timer = FirstAudio(clock)
    timer.turn_ended()
    clock.now = 1.8
    timer.started()
    assert "Latency: end of turn to first audio 800 ms" in info.text


def test_confirmed_danger_dates_from_the_first_agreeing_frame() -> None:
    tracker = ObservationTracker()
    tracker.update(frame(), 0.0)
    assert tracker.update(fight(), 1.3) == []
    [change] = tracker.update(fight(), 2.6)
    assert change.name == "danger_started" and change.since == 1.3


def test_high_danger_and_the_end_of_danger_date_from_their_first_frames() -> None:
    tracker = ObservationTracker()
    for ts in (0.0, 1.0):
        tracker.update(fight(), ts)
    tracker.update(fight("high"), 2.0)
    [high] = tracker.update(fight("high"), 3.0)
    assert high.name == "danger_high" and high.since == 2.0
    for ts in (4.0, 5.0):
        assert tracker.update(frame(), ts) == []
    [ended] = tracker.update(frame(), 6.0)
    assert ended.name == "danger_ended" and ended.since == 4.0


def test_low_health_dates_from_the_frame_before_it_was_confirmed() -> None:
    tracker = ObservationTracker()
    low = frame(health_raw="20/100", health_percent=20)
    tracker.update(frame(), 0.0)
    assert tracker.update(low, 1.3) == []
    [change] = tracker.update(low, 2.6)
    assert change.name == "health_low" and change.since == 1.3


def test_death_dates_from_the_first_death_screen() -> None:
    tracker = ObservationTracker()
    dead = frame(screen_type="death", health_visible=False)
    tracker.update(frame(), 0.0)
    assert tracker.update(dead, 1.3) == []
    [change] = tracker.update(dead, 2.6)
    assert change.name == "player_died" and change.since == 1.3


async def test_the_observer_stamps_events_with_the_frame_that_first_showed_them() -> None:
    bus = EventBus()
    events = bus.subscribe()
    built, _ = observer(FakeVision(), bus)
    built._apply(report(), 1.0)
    built._apply(report(), 1.8)
    published = events.get_nowait()
    assert isinstance(published, GameEvent) and published.frame_ts == 1.0


def test_reactions_carry_their_origin_without_changing_what_was_decided() -> None:
    state = DirectorState(bark_events={"danger_started": "danger"})
    [bark] = decide(GameEvent("danger_started", frame_ts=1.0, ts=2.0), state)
    assert bark == PlayBark("danger", "danger_started", {})
    assert isinstance(bark, PlayBark) and bark.origin == Origin("danger_started", "observer", 1, 2)

    [react] = decide(GameEvent("player_died", frame_ts=5.0, ts=6.0), DirectorState())
    assert react == ReactToEvent("player_died")
    assert isinstance(react, ReactToEvent) and react.origin is not None
    assert react.origin.frame_ts == 5.0


async def test_a_talker_reaction_hands_its_origin_to_the_voice() -> None:
    rig = Rig(talker=FakeTextLLM(["Ouch."]))
    seen = time.monotonic() - 2.0
    async with rig.running():
        await rig.publish(GameEvent("player_died", frame_ts=seen))
    assert rig.voice.said == ["Ouch."]
    [origin] = rig.voice.origins
    assert origin is not None and origin.frame_ts == seen and origin.event == "player_died"


async def test_a_bark_logs_frame_to_bark_and_hands_its_origin_to_the_voice(
    tmp_path: Path, info: pytest.LogCaptureFixture
) -> None:
    bank = BarkBank(BARK_BOOK, FakeBarkSynth(), tmp_path, "model", 24000)
    await bank.prepare("voiceA")
    rig = Rig(bark_events={"danger_started": "danger"}, barks=bank, voice_id="voiceA")
    async with rig.running():
        await rig.publish(
            GameEvent("danger_started", source="reader", frame_ts=time.monotonic() - 0.5)
        )
    assert [bark.text for bark in rig.voice.played] == ["Heads up."]
    assert "Latency: frame to bark" in info.text and "danger_started from reader" in info.text
    # The old line stays, so numbers from before WP9 can still be compared.
    assert "Latency: event to bark" in info.text
    [origin] = rig.voice.origins
    assert origin is not None and origin.source == "reader"


def test_replay_records_leave_out_this_processs_clock() -> None:
    record = event_record(GameEvent("danger_started", frame_ts=1.0), 2.5)
    assert record is not None
    assert "frame_ts" not in record.data and "ts" not in record.data
