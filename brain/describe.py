"""`python -m brain --describe`: what the Control Center can offer before the brain starts.

Only imports config and personalities, so it answers in about a second with no Pipecat or audio.
Reports whether each key is set, never its value.
"""

from brain.config import Settings
from brain.director.personalities import load_personalities
from shared.protocol import PROTOCOL_VERSION, BrainDescription

# Environment variable name -> Settings field. The Control Center offers exactly these.
KEY_FIELDS = {
    "GEMINI_API_KEY": "gemini_api_key",
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "DEEPGRAM_API_KEY": "deepgram_api_key",
    "ELEVENLABS_API_KEY": "elevenlabs_api_key",
    "EXA_API_KEY": "exa_api_key",
    "CARTESIA_API_KEY": "cartesia_api_key",
}


def describe(settings: Settings) -> BrainDescription:
    return BrainDescription(
        protocol_version=PROTOCOL_VERSION,
        personalities=load_personalities().names,
        voices=settings.voice_options,
        keys_set={name: getattr(settings, field) is not None for name, field in KEY_FIELDS.items()},
        game_title=settings.game_title,
        game_process=settings.game_process,
    )
