"""Voice output interface and the choice between implementations.

PipecatVoice (brain/voice/pipecat_voice.py) is the real one. SubtitleOnlyVoice stands in when the
voice keys aren't set, which keeps the overlay and tests usable with no API keys or microphone.
"""

import logging
import uuid
from typing import Protocol

from brain.config import Settings
from brain.events import EventBus
from brain.server import OverlayLink
from shared.protocol.messages import AvatarState, SubtitleChunk

log = logging.getLogger(__name__)


class Voice(Protocol):
    async def say(self, text: str) -> bool:
        """Returns whether the text was accepted to be spoken."""
        ...

    async def set_voice(self, voice_id: str | None) -> None: ...

    async def run(self) -> None: ...

    def live_state(self) -> dict[str, str]: ...


class SubtitleOnlyVoice:
    def __init__(self, link: OverlayLink) -> None:
        self._link = link

    async def say(self, text: str) -> bool:
        log.info("Say: %s", text)
        await self._link.send(AvatarState(state="talking"))
        await self._link.send(SubtitleChunk(utterance_id=uuid.uuid4().hex, text=text, final=True))
        await self._link.send(AvatarState(state="idle"))
        return True

    async def set_voice(self, voice_id: str | None) -> None:
        return

    async def run(self) -> None:
        return

    def live_state(self) -> dict[str, str]:
        return {}


def create_voice(settings: Settings, bus: EventBus, link: OverlayLink) -> Voice:
    if settings.deepgram_api_key is None:
        log.warning("Not listening or speaking: set DEEPGRAM_API_KEY to hear the player")
        return SubtitleOnlyVoice(link)
    if settings.elevenlabs_api_key is None or settings.elevenlabs_voice_id is None:
        log.warning("Listening, but replying in subtitles: set the ElevenLabs keys for speech")

    try:
        # Imported here so tests and key-less runs don't need PyAudio or the Pipecat services.
        from brain.voice.pipecat_voice import PipecatVoice

        return PipecatVoice(settings, bus, link)
    except Exception:
        # A missing audio device shouldn't stop the partner from watching the game.
        log.exception("Voice failed to start; falling back to subtitles")
        return SubtitleOnlyVoice(link)
