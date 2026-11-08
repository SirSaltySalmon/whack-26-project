"""Builds the vendor services PipecatVoice runs, so swapping one stays in one place."""

from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

from brain.config import Settings
from brain.voice.style import style_values


def flux_stt(settings: Settings, api_key: str) -> DeepgramFluxSTTService:
    return DeepgramFluxSTTService(
        api_key=api_key,
        settings=DeepgramFluxSTTService.Settings(
            model=settings.stt_model,
            eot_threshold=settings.stt_eot_threshold,
            eot_timeout_ms=settings.stt_eot_timeout_ms,
            keyterm=list(settings.stt_keyterms),
        ),
    )


def elevenlabs_tts(
    settings: Settings, api_key: str, voice_id: str, style: str
) -> ElevenLabsTTSService:
    return ElevenLabsTTSService(
        api_key=api_key,
        settings=ElevenLabsTTSService.Settings(
            model=settings.tts_model,
            voice=voice_id,
            **style_values(style),
        ),
    )
