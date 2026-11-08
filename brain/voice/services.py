"""Builds the vendor services PipecatVoice uses, so swapping one stays a change in one place."""

from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

from brain.config import Settings
from brain.voice.style import style_values


def make_stt(settings: Settings) -> DeepgramFluxSTTService:
    if settings.deepgram_api_key is None:
        raise ValueError("Speech recognition needs DEEPGRAM_API_KEY")
    return DeepgramFluxSTTService(
        api_key=settings.deepgram_api_key.get_secret_value(),
        settings=DeepgramFluxSTTService.Settings(
            model=settings.stt_model,
            eot_threshold=settings.stt_eot_threshold,
            eot_timeout_ms=settings.stt_eot_timeout_ms,
            keyterm=list(settings.stt_keyterms),
        ),
    )


def make_tts(settings: Settings, voice_id: str, style: str) -> ElevenLabsTTSService:
    if settings.elevenlabs_api_key is None:
        raise ValueError("Speech needs ELEVENLABS_API_KEY")
    return ElevenLabsTTSService(
        api_key=settings.elevenlabs_api_key.get_secret_value(),
        settings=ElevenLabsTTSService.Settings(
            model=settings.tts_model, voice=voice_id, **style_values(style)
        ),
    )
