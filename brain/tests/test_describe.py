from pydantic import SecretStr

from brain.config import Settings
from brain.describe import KEY_FIELDS, describe
from shared.protocol import BrainDescription
from shared.protocol.messages import VoiceOption

SECRET = "sk-very-secret-value-1234"


def test_reports_which_keys_are_set_but_never_their_values() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        gemini_api_key=SecretStr(SECRET),
        anthropic_api_key=None,
        deepgram_api_key=None,
        elevenlabs_api_key=None,
        exa_api_key=None,
        cartesia_api_key=None,
        voice_options=[VoiceOption(name="Ava", id="v1")],
    )

    text = describe(settings).model_dump_json()

    assert SECRET not in text
    parsed = BrainDescription.model_validate_json(text)
    assert parsed.keys_set["GEMINI_API_KEY"] is True
    assert parsed.keys_set["ANTHROPIC_API_KEY"] is False
    assert set(parsed.keys_set) == set(KEY_FIELDS)
    assert parsed.voices[0].id == "v1"
    assert "supportive" in parsed.personalities


def test_key_fields_exist_on_settings() -> None:
    assert set(KEY_FIELDS.values()) <= set(Settings.model_fields)
