"""Builds the vendor services PipecatVoice runs, so swapping a vendor stays a change in one place.

Kept apart from pipecat_voice.py, which is at the file length limit.
"""

from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams

from brain.config import Settings
from brain.voice.style import style_values


def local_audio(settings: Settings, speaks: bool) -> LocalAudioTransport:
    """The mic always; the speakers only when there's a voice to play."""
    return LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=speaks,
            input_device_index=settings.mic_device_index,
            output_device_index=settings.speaker_device_index,
        )
    )


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
            model=settings.tts_model, voice=voice_id, **style_values(style)
        ),
    )
