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

With the mic off in settings, EchoGate feeds Flux silence all the time, and any turn Flux still
reports is dropped, so speech starts no turn and no barge-in. The partner still talks and reacts,
and typed turns reach the bus from the overlay without passing through here.

Without ElevenLabs keys it still listens: transcripts and mood keep flowing, and replies go to
subtitles only.
"""

import asyncio
import logging
import time
import uuid

from pipecat.frames.frames import TTSSpeakFrame, TTSUpdateSettingsFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.workers.runner import WorkerRunner

from brain.config import Settings
from brain.events import (
    EventBus,
    PlayerMood,
    PlayerSpeech,
    PlayerSpeechPartial,
    PlayerStartedSpeaking,
    SettingsChanged,
)
from brain.latency import FirstAudio, Origin
from brain.server import OverlayLink
from brain.voice.barks import Bark
from brain.voice.pipeline import SubtitleOnlyVoice
from brain.voice.processors import EchoGate, SpokenOutputTap, TurnBridge, bark_frames
from brain.voice.self_echo import SelfEcho
from brain.voice.sentiment import Mood, MoodTracker
from brain.voice.services import elevenlabs_tts, flux_stt, local_audio
from brain.voice.style import style_values
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
        self._echo = SelfEcho()
        self._last_partial = ""
        self._last_partial_logged = 0.0
        self.bot_speaking = False
        self.user_speaking = False
        self._first_audio = FirstAudio()
        self._half_duplex = settings.voice_half_duplex
        self._echo_tail_s = settings.voice_echo_tail_ms / 1000
        self._bot_stopped_at: float | None = None
        # What check_mic last saw, so a change is acted on and logged once.
        self._mic_was_on = True
        if self._half_duplex:
            log.info("Half-duplex voice: mic muted while the partner talks; no barge-in")

        # A voice the player chose earlier beats the configured default.
        self._default_voice = settings.elevenlabs_voice_id
        voice_id = link.settings.voice_id or settings.elevenlabs_voice_id
        speaks = settings.elevenlabs_api_key is not None and bool(voice_id)
        self._speaks = speaks
        self._style: str = link.settings.voice_style
        # Subscribed now, so a style the Control Center sends on connect isn't missed.
        self._settings_events = bus.subscribe()
        transport = local_audio(settings, speaks)
        stt = flux_stt(settings, settings.deepgram_api_key.get_secret_value())
        self._bridge = TurnBridge(self)
        self._register_turn_events(stt)

        processors: list[FrameProcessor] = [
            transport.input(),
            EchoGate(self),
            stt,
            self._bridge,
        ]
        if settings.elevenlabs_api_key is not None and voice_id:
            api_key = settings.elevenlabs_api_key.get_secret_value()
            tts = elevenlabs_tts(settings, api_key, voice_id, self._style)
            processors += [tts, transport.output(), SpokenOutputTap(self)]
        pipeline = Pipeline(processors)
        self._worker = PipelineWorker(
            pipeline,
            params=PipelineParams(enable_metrics=True),
            # Quiet stretches are normal while someone plays, so never end the pipeline for it.
            idle_timeout_secs=None,
        )

    async def say(self, text: str, *, origin: Origin | None = None) -> bool:
        if self.user_speaking:
            # The director owns priorities; this only stops us talking over the player.
            # Debug, because the director retries results it still owes the player.
            log.debug("Player is talking; not saying: %s", text)
            return False
        if not self._speaks:
            return await self._subtitles.say(text)
        log.info("Say: %s", text)
        self._echo.said(text)
        self._first_audio.queued(origin, self.bot_speaking)
        await self._worker.queue_frame(TTSSpeakFrame(text))
        return True

    async def play(self, bark: Bark, *, origin: Origin | None = None) -> bool:
        if self.user_speaking:
            log.debug("Player is talking; not playing: %s", bark.text)
            return False
        if not self._speaks:
            return await self._subtitles.say(bark.text)
        log.info("Bark: %s", bark.text)
        self._echo.said(bark.text)
        # One chunk, because SpokenOutputTap only sees TTS text and a line this short needs no
        # word timing. It goes out as the audio is queued, which is within a chunk of it playing.
        await self.send(SubtitleChunk(utterance_id=uuid.uuid4().hex, text=bark.text, final=True))
        self._first_audio.queued(origin, self.bot_speaking)
        await self._worker.queue_frames(bark_frames(bark))
        return True

    async def set_voice(self, voice_id: str | None) -> None:
        voice_id = voice_id or self._default_voice
        if self._speaks and voice_id:
            delta = ElevenLabsTTSService.Settings(voice=voice_id)
            await self._worker.queue_frame(TTSUpdateSettingsFrame(delta=delta))

    async def set_style(self, style: str) -> None:
        """Applies from the next line spoken: Pipecat opens a new audio context with them."""
        if style == self._style:
            return
        self._style = style
        log.info("Voice style: %s", style)
        if self._speaks:
            delta = ElevenLabsTTSService.Settings(**style_values(style))
            await self._worker.queue_frame(TTSUpdateSettingsFrame(delta=delta))

    async def _follow_style(self) -> None:
        while True:
            event = await self._settings_events.get()
            if isinstance(event, SettingsChanged):
                style = getattr(event.settings, "voice_style", None)
                if isinstance(style, str):
                    await self.set_style(style)

    async def run(self) -> None:
        runner = WorkerRunner(handle_sigint=False)  # brain/__main__.py owns Ctrl+C
        await runner.add_workers(self._worker)
        styles = asyncio.create_task(self._follow_style(), name="Voice style")
        try:
            await runner.run()
        finally:
            styles.cancel()

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
        if not text or text == self._last_partial or not self.mic_on():
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
        self._first_audio.started()

    def on_bot_stopped(self) -> None:
        self.bot_speaking = False
        self._bot_stopped_at = time.monotonic()

    def mic_on(self) -> bool:
        """The player's setting, read live so turning it off takes effect on the next frame."""
        return self._link.settings.mic_enabled

    async def check_mic(self) -> None:
        """Acts on the player turning the mic on or off. EchoGate calls this for every frame."""
        on = self.mic_on()
        if on == self._mic_was_on:
            return
        self._mic_was_on = on
        log.info("Mic turned %s in settings", "on" if on else "off")
        if not on and self.user_speaking:
            # The end of this turn will be dropped, and until then say() would refuse every line.
            self.user_speaking = False
            await self.send(AvatarState(state="idle"))

    def mic_muted(self) -> bool:
        if not self.mic_on():
            return True
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
            if not self.mic_on():
                # Audio Flux had before the mic went off: no barge-in, and no "listening".
                log.debug("Mic off; ignored a start of turn")
                return
            self.user_speaking = True
            self._first_audio.turn_started()
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
            await self.on_end_of_turn(transcript)

    async def on_end_of_turn(self, transcript: str) -> None:
        self.user_speaking = False
        if not self.mic_on():
            # They turned the mic off mid-sentence, so the half they said isn't a turn. No
            # avatar change either: check_mic already reset it, and it may be talking now.
            log.info("Mic off; dropped the rest of a turn: %s", transcript.strip())
            return
        await self.send(AvatarState(state="idle"))
        transcript = transcript.strip()
        if not transcript:
            return
        if self._echo.is_echo(transcript):
            log.warning("Ignoring the partner's own voice, heard by the mic: %s", transcript)
            return
        self._first_audio.turn_ended()
        mood = self._mood.add_text(transcript, final=True)
        log.info("Player (%s): %s", mood.label if mood else "unknown", transcript)
        self._publish_mood(mood)
        self._bus.publish(PlayerSpeech(transcript=transcript))
