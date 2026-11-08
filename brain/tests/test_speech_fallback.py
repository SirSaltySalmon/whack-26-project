"""Lines still reach the screen when the TTS service fails, and speech gives up when it must."""

from typing import Any

import pytest

pytest.importorskip("pyaudio")
from pipecat.frames.frames import ErrorFrame  # noqa: E402
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor  # noqa: E402
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService  # noqa: E402
from pipecat.utils.errors import ErrorCategory  # noqa: E402

from brain.voice.processors import TurnBridge  # noqa: E402
from brain.voice.speech_fallback import FAILURES_BEFORE_GIVING_UP, SpeechFallback  # noqa: E402


class FakeSubtitles:
    def __init__(self) -> None:
        self.shown: list[str] = []

    async def say(self, text: str) -> bool:
        self.shown.append(text)
        return True


def _error(category: ErrorCategory | None = None, processor: Any = None) -> ErrorFrame:
    error = ErrorFrame(error="TTS context completed with no audio")
    error.category = category
    error.processor = processor
    return error


async def test_a_line_whose_speech_failed_is_shown_as_a_subtitle() -> None:
    subtitles = FakeSubtitles()
    speech = SpeechFallback(subtitles)
    speech.queued("first line")
    speech.queued("second line")
    await speech.failed(_error())
    assert subtitles.shown == ["first line"]
    assert not speech.given_up


async def test_speech_gives_up_after_failures_in_a_row() -> None:
    speech = SpeechFallback(FakeSubtitles())
    for _ in range(FAILURES_BEFORE_GIVING_UP - 1):
        await speech.failed(_error())
    assert not speech.given_up
    await speech.failed(_error())
    assert speech.given_up


async def test_a_line_that_played_resets_the_count() -> None:
    speech = SpeechFallback(FakeSubtitles())
    for _ in range(FAILURES_BEFORE_GIVING_UP - 1):
        await speech.failed(_error())
    speech.played()
    await speech.failed(_error())
    assert not speech.given_up


@pytest.mark.parametrize(
    "category", [ErrorCategory.AUTHENTICATION, ErrorCategory.AUTHORIZATION, ErrorCategory.QUOTA]
)
async def test_a_rejected_key_or_no_credits_gives_up_at_once(category: ErrorCategory) -> None:
    speech = SpeechFallback(FakeSubtitles())
    await speech.failed(_error(category))
    assert speech.given_up


async def test_a_network_blip_does_not_give_up_at_once() -> None:
    speech = SpeechFallback(FakeSubtitles())
    await speech.failed(_error(ErrorCategory.CONNECTIVITY))
    assert not speech.given_up


async def test_barge_in_forgets_lines_that_will_never_play() -> None:
    subtitles = FakeSubtitles()
    speech = SpeechFallback(subtitles)
    speech.queued("dropped by barge-in")
    speech.interrupted()
    await speech.failed(_error())
    assert subtitles.shown == []


class _Voice:
    def __init__(self) -> None:
        self.speech = SpeechFallback(FakeSubtitles())
        self.failures: list[ErrorFrame] = []

        async def failed(error: ErrorFrame) -> None:
            self.failures.append(error)

        self.speech.failed = failed  # type: ignore[method-assign]


async def _upstream(processor: FrameProcessor, frame: Any) -> list[Any]:
    pushed: list[Any] = []
    processor._enable_direct_mode = True

    async def push_frame(out: Any, _direction: FrameDirection = FrameDirection.UPSTREAM) -> None:
        pushed.append(out)

    processor.push_frame = push_frame  # type: ignore[method-assign]
    await processor.process_frame(frame, FrameDirection.UPSTREAM)
    return pushed


async def test_the_bridge_hands_tts_errors_to_the_fallback_and_passes_them_on() -> None:
    voice = _Voice()
    tts = ElevenLabsTTSService(api_key="test", settings=ElevenLabsTTSService.Settings(voice="v"))
    error = _error(processor=tts)
    assert await _upstream(TurnBridge(voice), error) == [error]  # type: ignore[arg-type]
    assert voice.failures == [error]


async def test_the_bridge_ignores_errors_from_anything_but_tts() -> None:
    voice = _Voice()
    error = _error(processor=TurnBridge(voice))  # type: ignore[arg-type]
    assert await _upstream(TurnBridge(voice), error) == [error]  # type: ignore[arg-type]
    assert voice.failures == []
