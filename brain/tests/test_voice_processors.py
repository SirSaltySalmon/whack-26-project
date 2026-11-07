"""The frame processors PipecatVoice adds to its pipeline, with no pipeline or audio devices."""

from typing import Any

import pytest

from shared.protocol.messages import AvatarState, SubtitleChunk

pytest.importorskip("pyaudio")
from pipecat.frames.frames import (  # noqa: E402
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    TextFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor  # noqa: E402

from brain.voice.processors import EchoGate, SpokenOutputTap, TurnBridge  # noqa: E402


class FakePipecatVoice:
    """What the processors use of PipecatVoice, recorded."""

    def __init__(self, muted: bool = False) -> None:
        self.muted = muted
        self.mic_audio: list[bytes] = []
        self.partials: list[str] = []
        self.sent: list[Any] = []
        self.started = 0
        self.stopped = 0

    def mic_muted(self) -> bool:
        return self.muted

    def on_mic_audio(self, pcm: bytes) -> None:
        self.mic_audio.append(pcm)

    def on_partial_transcript(self, text: str) -> None:
        self.partials.append(text)

    def on_bot_started(self) -> None:
        self.started += 1

    def on_bot_stopped(self) -> None:
        self.stopped += 1

    async def send(self, message: Any) -> None:
        self.sent.append(message)


async def _through(processor: FrameProcessor, frame: Any) -> list[Any]:
    """Runs a frame through one processor, returning what it passes on. Needs no pipeline."""
    pushed: list[Any] = []
    # Pipecat's own mode for running with no pipeline or tasks. Interruptions otherwise need both.
    processor._enable_direct_mode = True

    async def push_frame(out: Any, _direction: FrameDirection = FrameDirection.DOWNSTREAM) -> None:
        pushed.append(out)

    processor.push_frame = push_frame  # type: ignore[method-assign]
    await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
    return pushed


def test_the_processors_are_frame_processors_from_their_new_home() -> None:
    for processor in (EchoGate, TurnBridge, SpokenOutputTap):
        assert issubclass(processor, FrameProcessor)
        assert processor.__module__ == "brain.voice.processors"


def _mic_frame() -> InputAudioRawFrame:
    return InputAudioRawFrame(audio=b"\x01\x02" * 80, sample_rate=16000, num_channels=1)


async def test_echo_gate_passes_mic_audio_while_unmuted() -> None:
    voice = FakePipecatVoice(muted=False)
    frame = _mic_frame()
    pushed = await _through(EchoGate(voice), frame)  # type: ignore[arg-type]
    assert pushed == [frame]
    assert voice.mic_audio == [frame.audio]


async def test_echo_gate_swaps_in_the_same_length_of_silence_while_muted() -> None:
    voice = FakePipecatVoice(muted=True)
    frame = _mic_frame()
    pushed = await _through(EchoGate(voice), frame)  # type: ignore[arg-type]
    assert len(pushed) == 1 and pushed[0] is not frame
    assert pushed[0].audio == bytes(len(frame.audio))
    assert pushed[0].sample_rate == 16000 and pushed[0].num_channels == 1
    # The partner's own voice shouldn't colour the read of the player's mood.
    assert voice.mic_audio == []


async def test_echo_gate_leaves_other_frames_alone() -> None:
    voice = FakePipecatVoice(muted=True)
    frame = TextFrame(text="hello")
    assert await _through(EchoGate(voice), frame) == [frame]  # type: ignore[arg-type]
    assert voice.mic_audio == []


async def test_turn_bridge_passes_on_partial_transcripts() -> None:
    voice = FakePipecatVoice()
    frame = InterimTranscriptionFrame(text="where do", user_id="", timestamp="")
    assert await _through(TurnBridge(voice), frame) == [frame]  # type: ignore[arg-type]
    assert voice.partials == ["where do"]


def _word(text: str, context_id: str | None = "utterance-1") -> TTSTextFrame:
    return TTSTextFrame(text=text, text_type="word", context_id=context_id)


async def test_spoken_tap_sends_words_then_ends_the_utterance() -> None:
    voice = FakePipecatVoice()
    tap = SpokenOutputTap(voice)  # type: ignore[arg-type]
    for frame in (
        BotStartedSpeakingFrame(),
        _word("Nice"),
        _word("dodge"),
        BotStoppedSpeakingFrame(),
    ):
        assert await _through(tap, frame) == [frame]
    assert voice.sent == [
        AvatarState(state="talking"),
        SubtitleChunk(utterance_id="utterance-1", text="Nice"),
        SubtitleChunk(utterance_id="utterance-1", text="dodge"),
        SubtitleChunk(utterance_id="utterance-1", text="", final=True),
        AvatarState(state="idle"),
    ]
    assert (voice.started, voice.stopped) == (1, 1)


async def test_spoken_tap_ends_the_subtitle_when_interrupted() -> None:
    voice = FakePipecatVoice()
    tap = SpokenOutputTap(voice)  # type: ignore[arg-type]
    await _through(tap, _word("Nice"))
    await _through(tap, InterruptionFrame())
    assert voice.sent[-1] == SubtitleChunk(utterance_id="utterance-1", text="", final=True)
    # Still talking as far as this knows, until the output stops.
    assert voice.stopped == 0


async def test_spoken_tap_ends_an_utterance_only_once() -> None:
    voice = FakePipecatVoice()
    tap = SpokenOutputTap(voice)  # type: ignore[arg-type]
    await _through(tap, _word("Nice"))
    await _through(tap, InterruptionFrame())
    await _through(tap, BotStoppedSpeakingFrame())
    finals = [m for m in voice.sent if isinstance(m, SubtitleChunk) and m.final]
    assert len(finals) == 1


async def test_spoken_tap_makes_up_an_id_if_tts_has_none() -> None:
    voice = FakePipecatVoice()
    tap = SpokenOutputTap(voice)  # type: ignore[arg-type]
    await _through(tap, _word("Nice", context_id=None))
    await _through(tap, _word("dodge", context_id=None))
    ids = {message.utterance_id for message in voice.sent}
    assert len(ids) == 1 and ids != {""}
