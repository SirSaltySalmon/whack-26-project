"""The frame processors PipecatVoice adds to its pipeline. See its docstring for the layout."""

import uuid
from typing import TYPE_CHECKING

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    ErrorFrame,
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.tts_service import TTSService

from brain.voice.barks import Bark, split_pcm
from shared.protocol.messages import AvatarState, SubtitleChunk

if TYPE_CHECKING:
    from brain.voice.pipecat_voice import PipecatVoice


def bark_frames(bark: Bark) -> list[OutputAudioRawFrame]:
    """Data frames, so they queue behind any speech already in the TTS service, the output
    transport treats them as speech (bot-speaking state), and an interruption drops the rest."""
    return [
        OutputAudioRawFrame(audio=chunk, sample_rate=bark.sample_rate, num_channels=1)
        for chunk in split_pcm(bark.pcm, bark.sample_rate)
    ]


class EchoGate(FrameProcessor):
    """Swaps mic audio for silence while the mic is off, or the partner's voice may be in the room.

    Silence rather than dropped frames, so Flux keeps a continuous stream and its timing holds.
    """

    def __init__(self, voice: "PipecatVoice") -> None:
        super().__init__()
        self._voice = voice

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            await self._voice.check_mic()
            if self._voice.mic_muted():
                frame = InputAudioRawFrame(
                    audio=bytes(len(frame.audio)),
                    sample_rate=frame.sample_rate,
                    num_channels=frame.num_channels,
                )
            else:
                self._voice.on_mic_audio(frame.audio)
        await self.push_frame(frame, direction)


class TurnBridge(FrameProcessor):
    """Starts interruptions from inside the pipeline, and passes on partial transcripts.

    It sits just before the TTS service, so the service's errors pass it on their way upstream.
    """

    def __init__(self, voice: "PipecatVoice") -> None:
        super().__init__()
        self._voice = voice

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InterimTranscriptionFrame):
            self._voice.on_partial_transcript(frame.text)
        elif isinstance(frame, ErrorFrame) and isinstance(frame.processor, TTSService):
            await self._voice.speech.failed(frame)
        await self.push_frame(frame, direction)


class SpokenOutputTap(FrameProcessor):
    """Sits after transport.output(), where frames arrive as their audio plays.

    Placing it here is what keeps subtitles in step with speech. Each TTS context is one
    utterance: words go out as `final=False` chunks, then an empty `final=True` chunk ends it.
    """

    def __init__(self, voice: "PipecatVoice") -> None:
        super().__init__()
        self._voice = voice
        self._utterance_id: str | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        match frame:
            case TTSTextFrame():
                self._utterance_id = frame.context_id or self._utterance_id or uuid.uuid4().hex
                await self._voice.send(
                    SubtitleChunk(utterance_id=self._utterance_id, text=frame.text)
                )
            case BotStartedSpeakingFrame():
                self._voice.on_bot_started()
                await self._voice.send(AvatarState(state="talking"))
            case BotStoppedSpeakingFrame() | InterruptionFrame():
                await self._end_utterance()
                if isinstance(frame, BotStoppedSpeakingFrame):
                    self._voice.on_bot_stopped()
                    await self._voice.send(AvatarState(state="idle"))
        await self.push_frame(frame, direction)

    async def _end_utterance(self) -> None:
        if self._utterance_id is not None:
            await self._voice.send(
                SubtitleChunk(utterance_id=self._utterance_id, text="", final=True)
            )
            self._utterance_id = None
