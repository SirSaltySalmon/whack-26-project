import time

import pytest

from brain.config import Settings
from brain.events import EventBus
from brain.server import OverlayLink
from brain.voice.pipeline import SubtitleOnlyVoice, create_voice

pytest.importorskip("pyaudio")
from brain.voice.pipecat_voice import PipecatVoice  # noqa: E402


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
