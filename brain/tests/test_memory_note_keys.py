"""How a session note's drafted key is matched to what memory already holds.

The pairs come from a live Minecraft session where every answer was stored twice.
"""

import pytest

from brain.memory.note_keys import Key, existing_key, names_same, restates


@pytest.mark.parametrize(
    ("drafted", "recorded"),
    [
        (Key("player", "preferred playstyle"), Key("player", "playstyle")),
        (Key("player", "current goal"), Key("playthrough", "current goal")),
        (Key("player", "Nether and Ender Dragon progress"), Key("playthrough", "progress")),
        (Key("Player", "goal"), Key("player", "Current  Goal")),
    ],
)
def test_a_related_key_restates_what_was_recorded(drafted: Key, recorded: Key) -> None:
    assert restates(drafted, recorded)


@pytest.mark.parametrize(
    ("drafted", "recorded"),
    [
        # The exact key is how the note corrects a fact, so memory's trust rules settle it.
        (Key("player", "playstyle"), Key("Player", " playstyle ")),
        (Key("player", "game mode"), Key("playthrough", "progress")),
        # Only the player and their run are interchangeable subjects.
        (Key("base", "location"), Key("player", "location")),
        (Key("player", "location"), Key("Skeletron", "location")),
    ],
)
def test_an_exact_or_unrelated_key_is_not_a_restatement(drafted: Key, recorded: Key) -> None:
    assert not restates(drafted, recorded)


def test_a_drafted_key_lands_on_the_one_known_key_naming_the_same_thing() -> None:
    known = [Key("playthrough", "progress"), Key("playthrough", "game mode")]
    assert existing_key(Key("player", "Game  Mode"), known) == Key("playthrough", "game mode")


def test_a_drafted_key_already_known_exactly_is_kept() -> None:
    known = [Key("playthrough", "goal"), Key("player", "goal")]
    assert existing_key(Key("Player ", "goal"), known) == Key("Player ", "goal")


def test_a_drafted_key_with_no_match_is_left_alone() -> None:
    known = [Key("player", "goal"), Key("playthrough", "goal")]
    assert existing_key(Key("me", "goal"), known) == Key("me", "goal")
    assert existing_key(Key("player", "deaths"), known) == Key("player", "deaths")


def test_duplicate_known_keys_count_once() -> None:
    known = [Key("playthrough", "game mode"), Key("Playthrough", "game mode")]
    assert existing_key(Key("player", "game mode"), known) == Key("playthrough", "game mode")


def test_only_an_equal_attribute_names_the_same_thing() -> None:
    # A looser match could close a different fact, such as a world name for the player's name.
    assert not names_same(Key("player", "name"), Key("playthrough", "world name"))
    assert existing_key(Key("player", "goal"), [Key("playthrough", "current goal")]) == Key(
        "player", "goal"
    )
