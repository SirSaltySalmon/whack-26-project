"""Pipecat voice: Deepgram Flux in, ElevenLabs out, subtitles to the overlay in step with audio.

The pipeline holds no LLM. The director decides when to speak and calls brain.llm itself, so this
module only turns speech into bus events and text into speech:

    mic -> EchoGate -> Flux STT -> TurnBridge -> ElevenLabs TTS -> speakers -> SpokenOutputTap
                                      |                                          |
                                      +- interrupts on StartOfTurn               +- subtitles

Flux does its own turn detection, so there is no Silero VAD and no user aggregator. The aggregator
would normally own barge-in, so TurnBridge does it instead when Flux reports a start of turn.

Without headphones the mic hears the speakers and the partner interrupts itself. Half-duplex mode
(VOICE_HALF_DUPLEX=true) has EchoGate feed Flux silence while the partner talks, at the cost of
barge-in.
"""

import logging
import time
import uuid

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    TTSSpeakFrame,
    TTSTextFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.workers.runner import WorkerRunner

from brain.config import Settings
from brain.events import EventBus, PlayerSpeech, PlayerStartedSpeaking
from brain.server import OverlayLink
from shared.protocol.messages import AvatarState, BrainMessage, SubtitleChunk

log = logging.getLogger(__name__)


class EchoGate(FrameProcessor):
    """Swaps mic audio for silence while the partner's voice may be in the room.

    Silence rather than dropped frames, so Flux keeps a continuous stream and its timing holds.
    """

    def __init__(self, voice: "PipecatVoice") -> None:
        super().__init__()
        self._voice = voice

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame) and self._voice.mic_muted():
            frame = InputAudioRawFrame(
                audio=bytes(len(frame.audio)),
                sample_rate=frame.sample_rate,
                num_channels=frame.num_channels,
            )
        await self.push_frame(frame, direction)


class TurnBridge(FrameProcessor):
    """Pass-through that gives the voice a place in the pipeline to start interruptions from."""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
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


class PipecatVoice:
    def __init__(self, settings: Settings, bus: EventBus, link: OverlayLink) -> None:
        if settings.deepgram_api_key is None or settings.elevenlabs_api_key is None:
            raise ValueError("PipecatVoice needs DEEPGRAM_API_KEY and ELEVENLABS_API_KEY")
        if settings.elevenlabs_voice_id is None:
            raise ValueError("PipecatVoice needs ELEVENLABS_VOICE_ID")

        self._bus = bus
        self._link = link
        self.bot_speaking = False
        self.user_speaking = False
        self._end_of_turn_at: float | None = None
        self._half_duplex = settings.voice_half_duplex
        self._echo_tail_s = settings.voice_echo_tail_ms / 1000
        self._bot_stopped_at: float | None = None
        if self._half_duplex:
            log.info("Half-duplex voice: mic muted while the partner talks; no barge-in")

        transport = LocalAudioTransport(
            LocalAudioTransportParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                input_device_index=settings.mic_device_index,
                output_device_index=settings.speaker_device_index,
            )
        )
        stt = DeepgramFluxSTTService(
            api_key=settings.deepgram_api_key.get_secret_value(),
            settings=DeepgramFluxSTTService.Settings(
                model=settings.stt_model,
                eot_threshold=settings.stt_eot_threshold,
                eot_timeout_ms=settings.stt_eot_timeout_ms,
                keyterm=list(settings.stt_keyterms),
            ),
        )
        tts = ElevenLabsTTSService(
            api_key=settings.elevenlabs_api_key.get_secret_value(),
            settings=ElevenLabsTTSService.Settings(
                model=settings.tts_model,
                voice=settings.elevenlabs_voice_id,
            ),
        )
        self._bridge = TurnBridge()
        self._register_turn_events(stt)

        pipeline = Pipeline(
            [
                transport.input(),
                EchoGate(self),
                stt,
                self._bridge,
                tts,
                transport.output(),
                SpokenOutputTap(self),
            ]
        )
        self._worker = PipelineWorker(
            pipeline,
            params=PipelineParams(enable_metrics=True),
            # Quiet stretches are normal while someone plays, so never end the pipeline for it.
            idle_timeout_secs=None,
        )

    async def say(self, text: str) -> None:
        if self.user_speaking:
            # The director owns priorities; this only stops us talking over the player.
            log.info("Player is talking; dropped: %s", text)
            return
        log.info("Say: %s", text)
        await self._worker.queue_frame(TTSSpeakFrame(text))

    async def run(self) -> None:
        runner = WorkerRunner(handle_sigint=False)  # brain/__main__.py owns Ctrl+C
        await runner.add_workers(self._worker)
        await runner.run()

    async def send(self, message: BrainMessage) -> None:
        try:
            await self._link.send(message)
        except Exception:
            # A dropped overlay must never stop the audio.
            log.exception("Failed to send %s to the overlay", message.type)

    def on_bot_started(self) -> None:
        self.bot_speaking = True
        if self._end_of_turn_at is not None:
            ms = (time.monotonic() - self._end_of_turn_at) * 1000
            log.info("Latency: end of turn to first audio %.0f ms", ms)
            self._end_of_turn_at = None

    def on_bot_stopped(self) -> None:
        self.bot_speaking = False
        self._bot_stopped_at = time.monotonic()

    def mic_muted(self) -> bool:
        if not self._half_duplex:
            return False
        if self.bot_speaking:
            return True
        # The speakers and the room still ring for a moment after the last audio frame.
        stopped = self._bot_stopped_at
        return stopped is not None and time.monotonic() - stopped < self._echo_tail_s

    def _register_turn_events(self, stt: DeepgramFluxSTTService) -> None:
        @stt.event_handler("on_start_of_turn")
        async def _on_start(_service: DeepgramFluxSTTService, _transcript: str) -> None:
            self.user_speaking = True
            self._end_of_turn_at = None
            if self.bot_speaking:
                log.info("Barge-in: player started speaking")
            # Also clears speech that's queued but not yet playing.
            await self._bridge.broadcast_interruption()
            self._bus.publish(PlayerStartedSpeaking())
            await self.send(AvatarState(state="listening"))

        @stt.event_handler("on_end_of_turn")
        async def _on_end(_service: DeepgramFluxSTTService, transcript: str) -> None:
            self.user_speaking = False
            await self.send(AvatarState(state="idle"))
            transcript = transcript.strip()
            if not transcript:
                return
            self._end_of_turn_at = time.monotonic()
            log.info("Player: %s", transcript)
            self._bus.publish(PlayerSpeech(transcript=transcript))
