"""Turning parts off for a test run, and blank keys counting as no key."""

from pathlib import Path

import pytest

from brain.capture.ring_buffer import RingBuffer
from brain.config import Settings
from brain.events import EventBus
from brain.hud import build_hud
from brain.llm.base import LLMUnavailableError
from brain.llm.factory import LLMFactory
from brain.memory.db import Database, connect
from brain.parts import make_observer
from brain.server import OverlayLink
from brain.switches import apply_off, is_off, parse_off

KEYS = {
    "gemini_api_key": "g",
    "anthropic_api_key": "a",
    "deepgram_api_key": "d",
    "elevenlabs_api_key": "e",
}


def _settings(**values: object) -> Settings:
    return Settings(_env_file=None, **{**KEYS, **values})  # type: ignore[arg-type]


def test_parse_off_takes_commas_or_spaces_in_any_case() -> None:
    assert parse_off(" Observer, tts  wiki ") == {"observer", "tts", "wiki"}
    assert parse_off("") == set()


def test_parse_off_names_the_unknown_part() -> None:
    with pytest.raises(ValueError, match="haiku"):
        parse_off("observer,haiku")


def test_turning_off_anthropic_drops_only_its_key() -> None:
    settings = apply_off(_settings(), {"anthropic"})
    assert settings.anthropic_api_key is None
    assert settings.gemini_api_key is not None
    with pytest.raises(LLMUnavailableError):
        LLMFactory(settings).observer()
    # Close looks fall back to Gemini rather than going away.
    assert LLMFactory(settings).closeup() is not None


def test_turning_off_voice_drops_the_mic_and_speech_keys() -> None:
    settings = apply_off(_settings(), {"voice"})
    assert settings.deepgram_api_key is None
    assert settings.elevenlabs_api_key is None


def test_flag_and_setting_add_up() -> None:
    settings = apply_off(_settings(disable="tts"), {"observer"})
    assert is_off(settings, "tts") and is_off(settings, "observer")
    assert not is_off(settings, "wiki")
    assert settings.elevenlabs_api_key is None


def test_nothing_off_leaves_settings_alone() -> None:
    settings = _settings()
    assert apply_off(settings) is settings


def test_is_off_rejects_a_misspelt_part() -> None:
    with pytest.raises(KeyError):
        is_off(_settings(), "obsrver")


def test_observer_turned_off_is_never_built() -> None:
    settings = apply_off(_settings(), {"observer"})
    bus = EventBus()
    observer = make_observer(settings, LLMFactory(settings), RingBuffer(2), OverlayLink(bus), bus)
    assert observer is None


def test_blank_key_counts_as_unset() -> None:
    settings = Settings(_env_file=None, anthropic_api_key="  ", gemini_api_key="g")  # type: ignore[call-arg]
    assert settings.anthropic_api_key is None
    assert settings.gemini_api_key is not None


def test_blank_key_from_the_environment_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert Settings(_env_file=None).anthropic_api_key is None  # type: ignore[call-arg]


def test_learner_turned_off_leaves_the_readers_running(tmp_path: Path) -> None:
    settings = apply_off(_settings(), {"learner"})
    bus = EventBus()
    database = Database(connect(tmp_path / "brain.sqlite3"))
    hud = build_hud(
        settings,
        LLMFactory(settings),
        database,
        RingBuffer(2),
        OverlayLink(bus),
        bus,
        None,
        live=True,
    )
    try:
        assert hud.learner is None
        assert hud.readers is not None
    finally:
        hud.close()
        database.close()
