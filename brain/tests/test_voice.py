import time
from typing import Any

import pytest

from brain.config import Settings
from brain.events import EventBus, PlayerMood, PlayerSpeech, PlayerSpeechPartial
from brain.server import OverlayLink
from brain.tests.fakes import FakeOverlay
from brain.voice.barks import Bark
from brain.voice.pipeline import SubtitleOnlyVoice, create_voice
from brain.voice.sentiment import MoodTracker
from shared.protocol.messages import AvatarState, SubtitleChunk

pytest.importorskip("pyaudio")
from brain.voice.pipecat_voice import PipecatVoice  # noqa: E402
from brain.voice.self_echo import SelfEcho  # noqa: E402


def test_missing_voice_keys_fall_back_to_subtitles() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    bus = EventBus()
    assert isinstance(create_voice(settings, bus, OverlayLink(bus)), SubtitleOnlyVoice)


def _voice(half_duplex: bool) -> "PipecatVoice":
    # Skip __init__: these checks need no audio devices or vendor connections.
    voice = PipecatVoice.__new__(PipecatVoice)
    voice._half_duplex = half_duplex
    voice._echo_tail_s = 0.4
    voice._bot_stopped_at = None
    voice.bot_speaking = False
    return voice


def test_full_duplex_never_mutes_the_mic() -> None:
    voice = _voice(half_duplex=False)
    voice.bot_speaking = True
    assert not voice.mic_muted()


def test_half_duplex_mutes_while_talking_and_through_the_echo_tail() -> None:
    voice = _voice(half_duplex=True)
    assert not voice.mic_muted()
    voice.bot_speaking = True
    assert voice.mic_muted()
    voice.on_bot_stopped()
    assert voice.mic_muted()
    voice._bot_stopped_at = time.monotonic() - 1.0
    assert not voice.mic_muted()


def _listening_voice() -> tuple["PipecatVoice", EventBus]:
    bus = EventBus()
    voice = PipecatVoice.__new__(PipecatVoice)
    voice._bus = bus
    voice._mood = MoodTracker()
    voice._last_partial = ""
    voice._last_partial_logged = 0.0
    voice._echo = SelfEcho()
    voice._link = FakeOverlay()  # type: ignore[assignment]
    voice.user_speaking = True
    return voice, bus


def test_partial_transcripts_are_published_once_each() -> None:
    voice, bus = _listening_voice()
    events = bus.subscribe()
    voice.on_partial_transcript("where do")
    voice.on_partial_transcript("where do")
    voice.on_partial_transcript("  ")
    published = []
    while not events.empty():
        published.append(events.get_nowait())
    partials = [e.transcript for e in published if isinstance(e, PlayerSpeechPartial)]
    assert partials == ["where do"]


def test_partial_transcripts_update_the_players_mood() -> None:
    voice, bus = _listening_voice()
    events = bus.subscribe()
    voice.on_partial_transcript("I hate this stupid game")
    published = []
    while not events.empty():
        published.append(events.get_nowait())
    moods = [e for e in published if isinstance(e, PlayerMood)]
    assert moods and moods[0].label == "frustrated"
    assert voice.live_state() == {"player mood": "frustrated"}


def test_live_text_is_logged_but_not_on_every_update(caplog: pytest.LogCaptureFixture) -> None:
    voice, _ = _listening_voice()
    with caplog.at_level("INFO", logger="brain.voice.pipecat_voice"):
        voice.on_partial_transcript("where")
        voice.on_partial_transcript("where do")
    heard = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Hearing")]
    assert heard == ["Hearing: where"]


def test_mic_audio_only_counts_while_the_player_talks() -> None:
    voice, _ = _listening_voice()
    voice.user_speaking = False
    voice.on_mic_audio(bytes(320))
    assert voice._mood._fast_db is None
    voice.user_speaking = True
    voice.on_mic_audio(bytes(320))
    assert voice._mood._fast_db is not None


def test_voice_that_fails_to_start_falls_back_to_subtitles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*_: object) -> None:
        raise OSError("no audio device")

    monkeypatch.setattr("brain.voice.pipecat_voice.PipecatVoice", broken)
    settings = Settings(_env_file=None, deepgram_api_key="test")  # type: ignore[call-arg]
    bus = EventBus()
    assert isinstance(create_voice(settings, bus, OverlayLink(bus)), SubtitleOnlyVoice)


BARK = Bark(text="Your health looks low.", pcm=bytes(960), sample_rate=24000)


async def test_subtitle_voice_plays_a_bark_as_one_final_chunk() -> None:
    overlay = FakeOverlay()
    voice = SubtitleOnlyVoice(overlay)  # type: ignore[arg-type]
    assert await voice.play(BARK) is True
    chunks = [message for message in overlay.sent if isinstance(message, SubtitleChunk)]
    assert [(chunk.text, chunk.final) for chunk in chunks] == [("Your health looks low.", True)]
    states = [message.state for message in overlay.sent if isinstance(message, AvatarState)]
    assert states == ["talking", "idle"]


class FakeWorker:
    def __init__(self) -> None:
        self.queued: list[Any] = []

    async def queue_frame(self, frame: Any) -> None:
        self.queued.append(frame)

    async def queue_frames(self, frames: Any) -> None:
        self.queued.extend(frames)


def _speaking_voice(
    user_speaking: bool, overlay: FakeOverlay | None = None
) -> tuple["PipecatVoice", FakeWorker]:
    voice = PipecatVoice.__new__(PipecatVoice)
    worker = FakeWorker()
    voice._worker = worker  # type: ignore[assignment]
    voice._link = overlay or FakeOverlay()  # type: ignore[assignment]
    voice._speaks = True
    voice._echo = SelfEcho()
    voice.user_speaking = user_speaking
    return voice, worker


async def test_pipecat_voice_drops_a_bark_while_the_player_is_talking() -> None:
    voice, worker = _speaking_voice(user_speaking=True)
    assert await voice.play(BARK) is False
    assert worker.queued == []


async def test_pipecat_voice_queues_a_bark_as_20_ms_audio_chunks() -> None:
    from pipecat.frames.frames import OutputAudioRawFrame

    overlay = FakeOverlay()
    voice, worker = _speaking_voice(user_speaking=False, overlay=overlay)
    bark = Bark(text="Careful.", pcm=bytes(960 * 3 + 100), sample_rate=24000)
    assert await voice.play(bark) is True
    # Audio only, no live TTS: 20 ms at 24 kHz is 480 samples, 960 bytes.
    assert all(isinstance(frame, OutputAudioRawFrame) for frame in worker.queued)
    assert [len(frame.audio) for frame in worker.queued] == [960, 960, 960, 100]
    assert {(frame.sample_rate, frame.num_channels) for frame in worker.queued} == {(24000, 1)}
    chunks = [m for m in overlay.sent if isinstance(m, SubtitleChunk)]
    assert [(chunk.text, chunk.final) for chunk in chunks] == [("Careful.", True)]


async def test_pipecat_voice_without_speech_shows_a_bark_as_a_subtitle() -> None:
    overlay = FakeOverlay()
    voice, worker = _speaking_voice(user_speaking=False)
    voice._speaks = False
    voice._subtitles = SubtitleOnlyVoice(overlay)  # type: ignore[arg-type]
    assert await voice.play(BARK) is True
    assert worker.queued == []
    assert [m.text for m in overlay.sent if isinstance(m, SubtitleChunk)] == [BARK.text]


async def test_the_partners_own_voice_isnt_taken_as_a_player_turn() -> None:
    voice, bus = _listening_voice()
    events = bus.subscribe()
    voice._echo.said("I can't check that right now.")
    await voice.on_end_of_turn("I can't check that right now.")
    await voice.on_end_of_turn("What's that glowing thing over there?")
    published = []
    while not events.empty():
        published.append(events.get_nowait())
    turns = [e.transcript for e in published if isinstance(e, PlayerSpeech)]
    assert turns == ["What's that glowing thing over there?"]
