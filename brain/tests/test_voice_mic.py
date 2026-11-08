"""Mic off in settings: no turns and no barge-in from audio, while the partner keeps talking.

PipecatVoice is built without __init__, and its Flux turn handlers are registered on a stand-in,
so this needs no audio devices or Deepgram connection.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from brain.events import EventBus, PlayerSpeech, PlayerSpeechPartial, PlayerStartedSpeaking
from brain.tests.fakes import FakeOverlay, drain
from brain.voice.sentiment import MoodTracker
from shared.protocol.messages import AvatarState, Settings

pytest.importorskip("pyaudio")
from brain.voice.pipecat_voice import PipecatVoice  # noqa: E402

Handler = Callable[[Any, str], Awaitable[None]]


class FakeFlux:
    """Collects the turn handlers PipecatVoice registers, so a test can fire them."""

    def __init__(self) -> None:
        self.handlers: dict[str, Handler] = {}

    def event_handler(self, name: str) -> Callable[[Handler], Handler]:
        def register(handler: Handler) -> Handler:
            self.handlers[name] = handler
            return handler

        return register

    async def start(self) -> None:
        await self.handlers["on_start_of_turn"](self, "")

    async def end(self, transcript: str) -> None:
        await self.handlers["on_end_of_turn"](self, transcript)


class FakeBridge:
    def __init__(self) -> None:
        self.interruptions = 0

    async def broadcast_interruption(self) -> None:
        self.interruptions += 1


class Harness:
    def __init__(self) -> None:
        self.bus = EventBus()
        self.events = self.bus.subscribe()
        self.overlay = FakeOverlay()
        self.flux = FakeFlux()
        self.bridge = FakeBridge()
        voice = PipecatVoice.__new__(PipecatVoice)
        voice._bus = self.bus
        voice._link = self.overlay  # type: ignore[assignment]
        voice._mood = MoodTracker()
        voice._last_partial = ""
        voice._last_partial_logged = 0.0
        voice.user_speaking = False
        voice.bot_speaking = False
        voice._end_of_turn_at = None
        voice._half_duplex = False
        voice._echo_tail_s = 0.4
        voice._bot_stopped_at = None
        voice._mic_was_on = True
        voice._bridge = self.bridge  # type: ignore[assignment]
        voice._register_turn_events(self.flux)  # type: ignore[arg-type]
        self.voice = voice

    def set_mic(self, on: bool) -> None:
        self.overlay.settings = Settings(mic_enabled=on)

    def avatar(self) -> list[str]:
        return [m.state for m in self.overlay.sent if isinstance(m, AvatarState)]

    def published(self) -> list[object]:
        return list(drain(self.events))


def test_mic_off_mutes_even_without_half_duplex() -> None:
    h = Harness()
    assert not h.voice.mic_muted()
    h.set_mic(False)
    assert h.voice.mic_muted()


async def test_turning_the_mic_off_mid_turn_ends_it_once(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="brain.voice.pipecat_voice")
    h = Harness()
    await h.flux.start()
    assert h.voice.user_speaking and h.avatar() == ["listening"]

    h.set_mic(False)
    await h.voice.check_mic()
    await h.voice.check_mic()
    # Otherwise say() would refuse every line, waiting on a turn that will never end.
    assert not h.voice.user_speaking
    assert h.avatar() == ["listening", "idle"]
    assert caplog.text.count("Mic turned off") == 1


async def test_with_the_mic_off_speech_starts_no_turn_and_no_barge_in() -> None:
    h = Harness()
    h.set_mic(False)
    await h.voice.check_mic()
    await h.flux.start()
    await h.flux.end("where do I go")
    h.voice.on_partial_transcript("where do")
    assert h.published() == []
    assert h.bridge.interruptions == 0
    assert "listening" not in h.avatar()
    assert not h.voice.user_speaking


async def test_the_rest_of_a_turn_cut_off_by_the_mic_is_dropped() -> None:
    h = Harness()
    await h.flux.start()
    h.set_mic(False)
    await h.voice.check_mic()
    await h.flux.end("where do I")
    assert not any(isinstance(event, PlayerSpeech) for event in h.published())


async def test_turning_the_mic_back_on_brings_turns_back(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="brain.voice.pipecat_voice")
    h = Harness()
    h.set_mic(False)
    await h.voice.check_mic()
    h.set_mic(True)
    await h.voice.check_mic()
    assert not h.voice.mic_muted()
    assert "Mic turned on" in caplog.text

    await h.flux.start()
    h.voice.on_partial_transcript("where do")
    await h.flux.end("where do I go")
    kinds = [type(event) for event in h.published()]
    assert kinds[0] is PlayerStartedSpeaking
    assert PlayerSpeechPartial in kinds and kinds[-1] is PlayerSpeech
    assert h.bridge.interruptions == 1


async def test_interrupting_cuts_speech_and_resets_a_talking_avatar() -> None:
    h = Harness()
    h.voice.bot_speaking = True
    await h.voice.interrupt()
    assert h.bridge.interruptions == 1
    assert h.avatar() == ["idle"]
