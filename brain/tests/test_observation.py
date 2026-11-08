import pytest
from pydantic import ValidationError

from brain.perception.observation import OBSERVATION_PROMPT, Observation


def observation(**overrides: object) -> Observation:
    fields: dict[str, object] = {
        "screen_type": "gameplay",
        "summary": "Player fights a boss.",
        "player_action": None,
        "health_visible": True,
        "health_raw": None,
        "health_percent": None,
        "danger_level": "high",
        "threats": ["Boss"],
        "selected_item": None,
        "menu_title": None,
        "location": None,
        "on_screen_text": [],
        "notable": None,
        "unsure": [],
    }
    return Observation.model_validate({**fields, **overrides})


def test_health_numbers_on_screen_beat_the_models_percent() -> None:
    result = observation(health_raw="Life: 180/415", health_percent=72)
    assert result.health_fraction == pytest.approx(180 / 415)


def test_large_health_numbers_with_commas_are_read() -> None:
    assert observation(health_raw="1,500 / 3,000").health_fraction == pytest.approx(0.5)


def test_falls_back_to_percent_for_icons_and_bars() -> None:
    assert observation(health_raw="5 hearts", health_percent=100).health_fraction == 1.0


def test_impossible_numbers_fall_back_to_percent() -> None:
    assert observation(health_raw="500/100", health_percent=40).health_fraction == 0.4


def test_no_visible_health_means_no_fraction() -> None:
    assert observation(health_visible=False, health_raw="50/100").health_fraction is None


def test_unknown_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        observation(danger_level="extreme")


def test_the_prompt_prefers_plain_words_to_guessed_names() -> None:
    # A wrong boss or item name misleads the partner more than a plain description does.
    assert "only when that name is written on screen" in OBSERVATION_PROMPT
    assert "plain words" in OBSERVATION_PROMPT
