"""The demo is how Stage 0 gets checked by eye, so it must send every part, valid and well paced."""

import asyncio
import json
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from brain.config import Settings
from brain.director.personalities import load_personalities
from brain.events import EventBus, OverlayConnected, PlayerSpeech
from brain.server import OverlayLink, create_app
from brain.tests.fakes import FakeOverlay
from scripts.overlay_demo import (
    ANSWER_POLL_S,
    DEBUG_REGIONS_STALE_S,
    DEMO_VOICES,
    QUESTIONS,
    SPOKEN_WORDS,
    WHOLE_LINE,
    ask,
    offer_settings,
    one_pass,
    watch,
)
from shared.protocol import PROTOCOL_VERSION, BrainMessage, BrainMessageAdapter
from shared.protocol.messages import (
    AvatarState,
    CardShow,
    DebugRegions,
    MemoryToast,
    PointerFly,
    SettingsState,
    SubtitleChunk,
    VoiceOption,
)

# How long the overlay keeps each thing up. See useCompanionFeed.ts and Toasts.tsx.
OVERLAY_SUBTITLE_LINGER_S = 2.5
OVERLAY_TOAST_S = 4.0
BRAIN_QUESTION_TIMEOUT_S = Settings.model_fields["question_answer_timeout_s"].default


class Clock:
    """Stands in for asyncio.sleep, so pacing can be checked with no real waiting."""

    def __init__(self) -> None:
        self.now = 0.0

    async def sleep(self, seconds: float) -> None:
        self.now += seconds
        await asyncio.sleep(0)


class TimedOverlay(FakeOverlay):
    def __init__(self, clock: Clock) -> None:
        super().__init__()
        self._clock = clock
        self.times: list[float] = []

    async def send(self, message: BrainMessage) -> None:
        self.times.append(self._clock.now)
        await super().send(message)

    def when(self, message: BrainMessage) -> float:
        return self.times[next(i for i, sent in enumerate(self.sent) if sent is message)]


async def run_one_pass() -> TimedOverlay:
    clock = Clock()
    overlay = TimedOverlay(clock)
    await one_pass(overlay, asyncio.Event(), clock.sleep)
    return overlay


def subtitles(overlay: FakeOverlay) -> list[SubtitleChunk]:
    return [message for message in overlay.sent if isinstance(message, SubtitleChunk)]


def toasts(overlay: FakeOverlay) -> list[MemoryToast]:
    return [message for message in overlay.sent if isinstance(message, MemoryToast)]


def questions(overlay: FakeOverlay) -> list[SubtitleChunk]:
    return [chunk for chunk in subtitles(overlay) if chunk.text in QUESTIONS]


async def until(condition: Callable[[], bool]) -> None:
    for _ in range(10_000):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError("The demo never got there")


async def test_every_message_in_a_pass_survives_the_protocol_round_trip() -> None:
    overlay = await run_one_pass()
    assert overlay.sent
    for message in overlay.sent:
        assert BrainMessageAdapter.validate_json(message.model_dump_json()) == message


async def test_a_pass_shows_every_part_of_the_overlay() -> None:
    overlay = await run_one_pass()
    kinds = {type(message) for message in overlay.sent}
    assert kinds == {AvatarState, PointerFly, DebugRegions, SubtitleChunk, MemoryToast}


def spoken(overlay: FakeOverlay) -> list[SubtitleChunk]:
    """Subtitles apart from the spoken questions."""
    return [chunk for chunk in subtitles(overlay) if chunk.text not in QUESTIONS]


async def test_debug_regions_keep_coming_until_an_empty_list_clears_them() -> None:
    overlay = await run_one_pass()
    sent = [message for message in overlay.sent if isinstance(message, DebugRegions)]
    assert len(sent[0].regions) == 2
    assert sent[-1].regions == [] and all(message.regions for message in sent[:-1])
    times = [overlay.when(message) for message in sent]
    assert all(
        later - earlier < DEBUG_REGIONS_STALE_S
        for earlier, later in zip(times, times[1:], strict=False)
    )


async def test_word_chunks_then_an_empty_final_share_one_utterance() -> None:
    chunks = spoken(await run_one_pass())
    words = chunks[:-1]
    assert len({chunk.utterance_id for chunk in words}) == 1
    assert [chunk.text for chunk in words[:-1]] == list(SPOKEN_WORDS)
    assert not any(chunk.final for chunk in words[:-1])
    assert words[-1].text == "" and words[-1].final


async def test_the_one_chunk_line_is_a_separate_utterance_with_all_its_text() -> None:
    chunks = spoken(await run_one_pass())
    assert chunks[-1].text == WHOLE_LINE and chunks[-1].final
    assert chunks[-1].utterance_id != chunks[0].utterance_id


async def test_each_pass_uses_new_utterances_so_words_cant_join_an_old_line() -> None:
    clock = Clock()
    overlay = TimedOverlay(clock)
    answered = asyncio.Event()
    await one_pass(overlay, answered, clock.sleep)
    await one_pass(overlay, answered, clock.sleep)
    assert len({chunk.utterance_id for chunk in subtitles(overlay)}) == 8


async def test_a_toast_appears_for_every_source() -> None:
    assert {toast.source for toast in toasts(await run_one_pass())} == {
        "player",
        "observed",
        "wiki",
    }


async def test_questions_are_spoken_as_whole_lines() -> None:
    asked = questions(await run_one_pass())
    assert [chunk.text for chunk in asked] == list(QUESTIONS)
    assert all(chunk.final for chunk in asked)


async def test_the_next_subtitle_waits_for_the_finished_one_to_fade() -> None:
    overlay = await run_one_pass()
    chunks = spoken(overlay)
    gap = overlay.when(chunks[-1]) - overlay.when(chunks[-2])
    assert gap >= OVERLAY_SUBTITLE_LINGER_S


async def test_words_arrive_over_time_rather_than_all_at_once() -> None:
    overlay = await run_one_pass()
    words = spoken(overlay)[:-1]
    assert overlay.when(words[-1]) - overlay.when(words[0]) > 1.0


async def test_toasts_have_left_before_the_question_is_asked() -> None:
    overlay = await run_one_pass()
    assert overlay.when(questions(overlay)[0]) - overlay.when(toasts(overlay)[-1]) >= (
        OVERLAY_TOAST_S
    )


async def test_an_unanswered_question_is_held_as_long_as_the_brain_waits() -> None:
    overlay = await run_one_pass()
    first, second = questions(overlay)
    assert overlay.when(second) - overlay.when(first) >= BRAIN_QUESTION_TIMEOUT_S


async def test_answering_moves_on_without_waiting_out_the_hold() -> None:
    clock = Clock()
    overlay = TimedOverlay(clock)
    answered = asyncio.Event()

    async def answered_during_the_first_wait(seconds: float) -> None:
        answered.set()
        await clock.sleep(seconds)

    await ask(overlay, QUESTIONS[0], answered, answered_during_the_first_wait)
    assert clock.now == ANSWER_POLL_S


async def test_an_old_answer_cant_skip_the_next_question() -> None:
    clock = Clock()
    answered = asyncio.Event()
    answered.set()
    await ask(TimedOverlay(clock), QUESTIONS[0], answered, clock.sleep)
    assert clock.now >= BRAIN_QUESTION_TIMEOUT_S


async def test_connecting_starts_the_demo_and_a_typed_reply_moves_it_on() -> None:
    bus = EventBus()
    clock = Clock()
    overlay = TimedOverlay(clock)
    watcher = asyncio.create_task(watch(bus, overlay, clock.sleep))
    await asyncio.sleep(0)
    bus.publish(OverlayConnected(display_scale=1.0))

    await until(lambda: len(questions(overlay)) == 1)
    first = questions(overlay)[0]
    bus.publish(PlayerSpeech(transcript="exploring"))
    await until(lambda: len(questions(overlay)) == 2)

    assert overlay.when(questions(overlay)[1]) - overlay.when(first) < BRAIN_QUESTION_TIMEOUT_S
    watcher.cancel()
    with pytest.raises(asyncio.CancelledError):
        await watcher


async def test_reconnecting_restarts_the_demo_and_stopping_stops_it() -> None:
    bus = EventBus()
    clock = Clock()
    overlay = FakeOverlay()
    watcher = asyncio.create_task(watch(bus, overlay, clock.sleep))
    await asyncio.sleep(0)

    def cards() -> int:
        return sum(isinstance(message, CardShow) for message in overlay.sent)

    bus.publish(OverlayConnected(display_scale=1.0))
    await until(lambda: cards() == 2)
    bus.publish(OverlayConnected(display_scale=1.0))
    await until(lambda: cards() == 4)

    watcher.cancel()
    with pytest.raises(asyncio.CancelledError):
        await watcher
    await asyncio.sleep(0)
    stopped_at = len(overlay.sent)
    for _ in range(50):
        await asyncio.sleep(0)
    assert len(overlay.sent) == stopped_at


def connect_and_read_settings(link: OverlayLink) -> SettingsState:
    ready = {
        "type": "overlay.ready",
        "protocol_version": PROTOCOL_VERSION,
        "display_scale": 1.0,
        "width": 1280,
        "height": 720,
    }
    with TestClient(create_app(link)).websocket_connect("/ws") as socket:
        socket.send_text(json.dumps(ready))
        return SettingsState.model_validate(socket.receive_json())


def test_the_settings_panel_gets_real_personalities_and_demo_voices() -> None:
    link = OverlayLink(EventBus())
    offer_settings(link, Settings(_env_file=None))  # type: ignore[call-arg]
    state = connect_and_read_settings(link)
    assert state.personalities == load_personalities().names
    assert state.voices == DEMO_VOICES


def test_configured_voices_are_offered_instead_of_the_demo_ones() -> None:
    voice = VoiceOption(name="Rachel", id="configured")
    link = OverlayLink(EventBus())
    offer_settings(link, Settings(_env_file=None, voice_options=[voice]))  # type: ignore[call-arg]
    assert connect_and_read_settings(link).voices == [voice]
