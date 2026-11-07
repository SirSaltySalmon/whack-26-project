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
    async def say(self, text: str) -> None: ...

    async def run(self) -> None: ...


class SubtitleOnlyVoice:
    def __init__(self, link: OverlayLink) -> None:
        self._link = link

    async def say(self, text: str) -> None:
        log.info("Say: %s", text)
        await self._link.send(AvatarState(state="talking"))
        await self._link.send(SubtitleChunk(utterance_id=uuid.uuid4().hex, text=text, final=True))
        await self._link.send(AvatarState(state="idle"))

    async def run(self) -> None:
        return


def create_voice(settings: Settings, bus: EventBus, link: OverlayLink) -> Voice:
    missing = [
        name
        for name, value in (
            ("DEEPGRAM_API_KEY", settings.deepgram_api_key),
            ("ELEVENLABS_API_KEY", settings.elevenlabs_api_key),
            ("ELEVENLABS_VOICE_ID", settings.elevenlabs_voice_id),
        )
        if value is None
    ]
    if missing:
        log.warning("Voice is subtitles only; set %s for speech", ", ".join(missing))
        return SubtitleOnlyVoice(link)

    # Imported here so tests and key-less runs don't need PyAudio or the Pipecat services.
    from brain.voice.pipecat_voice import PipecatVoice

    return PipecatVoice(settings, bus, link)
