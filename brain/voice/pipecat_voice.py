"""Pipecat voice: Deepgram Flux in, ElevenLabs out, subtitles to the overlay in step with audio.

The pipeline holds no LLM. The director decides when to speak and calls brain.llm itself, so this
module only turns speech into bus events and text into speech:

    mic -> EchoGate -> Flux STT -> TurnBridge -> ElevenLabs TTS -> speakers -> SpokenOutputTap
             |                       |                                          |
             +- loudness (mood)      +- interrupts, partial transcripts         +- subtitles

Flux does its own turn detection, so there is no Silero VAD and no user aggregator. The aggregator
would normally own barge-in, so TurnBridge does it instead when Flux reports a start of turn.

Without headphones the mic hears the speakers and the partner interrupts itself. Half-duplex mode
(VOICE_HALF_DUPLEX=true) has EchoGate feed Flux silence while the partner talks, at the cost of
barge-in.

Without ElevenLabs keys it still listens: transcripts and mood keep flowing, and replies go to
subtitles only.
"""

import logging
import time
import uuid

from pipecat.frames.frames import OutputAudioRawFrame, TTSSpeakFrame, TTSUpdateSettingsFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.workers.runner import WorkerRunner

from brain.config import Settings
from brain.events import (
    EventBus,
    PlayerMood,
    PlayerSpeech,
    PlayerSpeechPartial,
    PlayerStartedSpeaking,
)
from brain.server import OverlayLink
from brain.voice.barks import Bark, split_pcm
from brain.voice.pipeline import SubtitleOnlyVoice
from brain.voice.processors import EchoGate, SpokenOutputTap, TurnBridge
from brain.voice.sentiment import Mood, MoodTracker
from shared.protocol.messages import AvatarState, BrainMessage, SubtitleChunk

log = logging.getLogger(__name__)

# Flux updates several times a second, and each update repeats the whole turn so far.
PARTIAL_LOG_INTERVAL_S = 1.0


class PipecatVoice:
    def __init__(self, settings: Settings, bus: EventBus, link: OverlayLink) -> None:
        if settings.deepgram_api_key is None:
            raise ValueError("PipecatVoice needs DEEPGRAM_API_KEY")

        self._bus = bus
        self._link = link
        self._subtitles = SubtitleOnlyVoice(link)
        self._mood = MoodTracker()
        self._last_partial = ""
        self._last_partial_logged = 0.0
        self.bot_speaking = False
        self.user_speaking = False
        self._end_of_turn_at: float | None = None
        self._half_duplex = settings.voice_half_duplex
        self._echo_tail_s = settings.voice_echo_tail_ms / 1000
        self._bot_stopped_at: float | None = None
        if self._half_duplex:
            log.info("Half-duplex voice: mic muted while the partner talks; no barge-in")

        # A voice the player chose earlier beats the configured default.
        self._default_voice = settings.elevenlabs_voice_id
        voice_id = link.settings.voice_id or settings.elevenlabs_voice_id
        speaks = settings.elevenlabs_api_key is not None and bool(voice_id)
        self._speaks = speaks
        transport = LocalAudioTransport(
            LocalAudioTransportParams(
                audio_in_enabled=True,
                audio_out_enabled=speaks,
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
        self._bridge = TurnBridge(self)
        self._register_turn_events(stt)

        processors: list[FrameProcessor] = [
            transport.input(),
            EchoGate(self),
            stt,
            self._bridge,
        ]
        if settings.elevenlabs_api_key is not None and voice_id:
            tts = ElevenLabsTTSService(
                api_key=settings.elevenlabs_api_key.get_secret_value(),
                settings=ElevenLabsTTSService.Settings(
                    model=settings.tts_model,
                    voice=voice_id,
                ),
            )
            processors += [tts, transport.output(), SpokenOutputTap(self)]
        pipeline = Pipeline(processors)
        self._worker = PipelineWorker(
            pipeline,
            params=PipelineParams(enable_metrics=True),
            # Quiet stretches are normal while someone plays, so never end the pipeline for it.
            idle_timeout_secs=None,
        )

    async def say(self, text: str) -> bool:
        if self.user_speaking:
            # The director owns priorities; this only stops us talking over the player.
            # Debug, because the director retries results it still owes the player.
            log.debug("Player is talking; not saying: %s", text)
            return False
        if not self._speaks:
            return await self._subtitles.say(text)
        log.info("Say: %s", text)
        await self._worker.queue_frame(TTSSpeakFrame(text))
        return True

    async def play(self, bark: Bark) -> bool:
        if self.user_speaking:
            log.debug("Player is talking; not playing: %s", bark.text)
            return False
        if not self._speaks:
            return await self._subtitles.say(bark.text)
        log.info("Bark: %s", bark.text)
        # One chunk, because SpokenOutputTap only sees TTS text and a line this short needs no
        # word timing. It goes out as the audio is queued, which is within a chunk of it playing.
        await self.send(SubtitleChunk(utterance_id=uuid.uuid4().hex, text=bark.text, final=True))
        # Data frames, so they queue behind any speech already in the TTS service, the output
        # transport treats them as speech (bot-speaking state), and an interruption drops the rest.
        frames = [
            OutputAudioRawFrame(audio=chunk, sample_rate=bark.sample_rate, num_channels=1)
            for chunk in split_pcm(bark.pcm, bark.sample_rate)
        ]
        await self._worker.queue_frames(frames)
        return True

    async def set_voice(self, voice_id: str | None) -> None:
        voice_id = voice_id or self._default_voice
        if self._speaks and voice_id:
            delta = ElevenLabsTTSService.Settings(voice=voice_id)
            await self._worker.queue_frame(TTSUpdateSettingsFrame(delta=delta))

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

    def live_state(self) -> dict[str, str]:
        return self._mood.live_state()

    def on_mic_audio(self, pcm: bytes) -> None:
        if self.user_speaking:
            self._mood.add_audio(pcm)

    def on_partial_transcript(self, text: str) -> None:
        text = text.strip()
        if not text or text == self._last_partial:
            return
        self._last_partial = text
        now = time.monotonic()
        if now - self._last_partial_logged >= PARTIAL_LOG_INTERVAL_S:
            self._last_partial_logged = now
            log.info("Hearing: %s", text)
        self._bus.publish(PlayerSpeechPartial(transcript=text))
        self._publish_mood(self._mood.add_text(text))

    def _publish_mood(self, mood: Mood | None) -> None:
        if mood is not None:
            log.debug("Player mood: %s", mood)
            self._bus.publish(PlayerMood(mood.label, mood.valence, mood.intensity))

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
            self._last_partial = ""
            self._mood.start_turn()
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
            mood = self._mood.add_text(transcript, final=True)
            log.info("Player (%s): %s", mood.label if mood else "unknown", transcript)
            self._publish_mood(mood)
            self._bus.publish(PlayerSpeech(transcript=transcript))
