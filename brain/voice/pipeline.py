"""Voice output interface.

TODO(track 3): add a Pipecat implementation using DeepgramFluxSTTService from
pipecat.services.deepgram.flux.stt with ElevenLabs TTS. Flux handles turn detection, so don't add
Silero to the voice path. Publish PlayerSpeech and PlayerStartedSpeaking on the bus.
"""

import logging
import uuid
from typing import Protocol

from brain.server import OverlayLink
from shared.protocol.messages import AvatarState, SubtitleChunk

log = logging.getLogger(__name__)


class Voice(Protocol):
    async def say(self, text: str) -> None: ...


class SubtitleOnlyVoice:
    """Stands in until Pipecat lands, and keeps the overlay testable with no API keys."""

    def __init__(self, link: OverlayLink) -> None:
        self._link = link

    async def say(self, text: str) -> None:
        log.info("Say: %s", text)
        await self._link.send(AvatarState(state="talking"))
        await self._link.send(SubtitleChunk(utterance_id=uuid.uuid4().hex, text=text, final=True))
        await self._link.send(AvatarState(state="idle"))
