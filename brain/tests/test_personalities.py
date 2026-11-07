import json
import re
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from brain.director.personalities import LineKind, PersonalityBook, load_personalities
from brain.director.talker import USUAL_WORDS

BOOK = load_personalities()
KINDS: tuple[str, ...] = get_args(LineKind)
# Canned lines are said over gameplay, so they keep to a short reply, not the cap for detail.
MAX_WORDS = USUAL_WORDS
ROOT = Path(__file__).resolve().parents[2]
# Words with a capital that aren't names, for the check on proper nouns below.
_ALWAYS_CAPITALIZED = {"I", "I'm", "I'll", "I've", "I'd"}


def _book(**changes: Any) -> dict[str, Any]:
    return {
        "default": "calm",
        "personalities": {"calm": {"tone": "Calm.", "lines": {"died": ["One.", "Two.", "Three."]}}},
        **changes,
    }


def _all_lines() -> list[str]:
    return [
        line
        for personality in BOOK.personalities.values()
        for lines in personality.lines.values()
        for line in lines
    ]


@pytest.mark.parametrize("name", BOOK.names)
@pytest.mark.parametrize("kind", KINDS)
def test_every_personality_has_a_line_for_every_kind(name: str, kind: LineKind) -> None:
    # The director asks for these by name, so a gap would only show up as an error in a live turn.
    assert BOOK.personalities[name].lines.get(kind), f"{name} has no {kind} lines"


def test_every_line_stays_within_the_word_cap() -> None:
    assert MAX_WORDS == 12
    assert [line for line in _all_lines() if len(line.split()) > MAX_WORDS] == []


def test_no_line_is_blank() -> None:
    assert [line for line in _all_lines() if not line.strip()] == []


def test_every_personality_has_a_tone() -> None:
    assert all(personality.tone.strip() for personality in BOOK.personalities.values())


def test_the_default_personality_exists() -> None:
    assert BOOK.default in BOOK.names


def test_event_lines_map_the_events_the_observer_raises_to_their_lines() -> None:
    assert BOOK.event_lines == {
        "danger_started": "danger",
        "danger_high": "danger_high",
        "player_died": "died",
        "health_low": "low_health",
    }


def test_event_lines_only_point_at_real_kinds() -> None:
    assert set(BOOK.event_lines.values()) <= set(KINDS)


def test_event_lines_with_an_unknown_kind_are_rejected() -> None:
    with pytest.raises(ValidationError):
        PersonalityBook.model_validate(_book(event_lines={"danger_started": "panic"}))


def test_a_line_of_an_unknown_kind_is_rejected() -> None:
    bad = {"calm": {"tone": "Calm.", "lines": {"panic": ["Oh no."]}}}
    with pytest.raises(ValidationError):
        PersonalityBook.model_validate(_book(personalities=bad))


def test_a_book_with_no_event_lines_sends_every_event_to_the_talker() -> None:
    assert PersonalityBook.model_validate(_book()).event_lines == {}


def test_line_cycles_through_the_lines_by_turn() -> None:
    book = PersonalityBook.model_validate(_book())
    said = [book.line("calm", "died", turn) for turn in range(7)]
    assert said == ["One.", "Two.", "Three.", "One.", "Two.", "Three.", "One."]


def test_an_unknown_personality_falls_back_to_the_default() -> None:
    # A setting saved before a personality was renamed shouldn't stop the partner talking.
    assert BOOK.line("renamed_since", "died", 0) == BOOK.line(BOOK.default, "died", 0)
    assert BOOK.tone("renamed_since") == BOOK.tone(BOOK.default)


def test_a_personality_can_be_added_with_data_alone(tmp_path: Path) -> None:
    path = tmp_path / "personalities.json"
    path.write_text(json.dumps(_book()), encoding="utf-8")
    assert load_personalities(path).line("calm", "died", 1) == "Two."


def _proper_nouns(text: str) -> list[str]:
    """Capitalized words past the start of a sentence, which is how a game's name would appear."""
    found: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        for word in sentence.split()[1:]:
            bare = word.strip(".,!?;:\"'()")
            if bare[:1].isupper() and bare not in _ALWAYS_CAPITALIZED:
                found.append(bare)
    return found


def test_the_proper_noun_check_would_catch_a_name() -> None:
    assert _proper_nouns("Watch out for Some Title, love.") == ["Some", "Title"]
    assert _proper_nouns("Hold on. I'm checking.") == []


def test_no_line_or_tone_names_a_specific_game() -> None:
    # The demo game's name comes from the project notes, so this file doesn't spell one out.
    notes = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    match = re.search(r"Demo game: (\w+)", notes)
    assert match is not None, "CLAUDE.md should name the demo game"
    demo_game = match.group(1).lower()

    tones = [personality.tone for personality in BOOK.personalities.values()]
    texts = tones + _all_lines()
    assert [text for text in texts if demo_game in text.lower()] == []
    assert [noun for text in texts for noun in _proper_nouns(text)] == []
