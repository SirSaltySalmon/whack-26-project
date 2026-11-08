"""The frame processors PipecatVoice adds to its pipeline. See its docstring for the layout."""

import uuid
from typing import TYPE_CHECKING

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from shared.protocol.messages import AvatarState, SubtitleChunk

if TYPE_CHECKING:
    from brain.voice.pipecat_voice import PipecatVoice


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
    """Starts interruptions from inside the pipeline, and passes on partial transcripts."""

    def __init__(self, voice: "PipecatVoice") -> None:
        super().__init__()
        self._voice = voice

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InterimTranscriptionFrame):
            self._voice.on_partial_transcript(frame.text)
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
