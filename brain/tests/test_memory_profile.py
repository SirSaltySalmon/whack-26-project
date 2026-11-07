import logging
import sqlite3

import pytest
from pydantic import BaseModel

from brain.memory.db import connect
from brain.memory.models import GameProfile
from brain.memory.profile import PlayerStore, ProfileStore


class SampleSettings(BaseModel):
    proactive: bool = True
    personality: str = "supportive"


@pytest.fixture
def conn() -> sqlite3.Connection:
    return connect(":memory:")


def test_unknown_game_gets_an_empty_profile(conn: sqlite3.Connection) -> None:
    assert ProfileStore(conn).get("Some Game") == GameProfile(game="Some Game", brief="", data={})


def test_merge_keeps_keys_it_does_not_mention(conn: sqlite3.Connection) -> None:
    store = ProfileStore(conn)
    store.merge_data("g", {"regions": {"hp": [0, 0, 1, 1]}})
    merged = store.merge_data("g", {"entity_types": ["boss"]})
    assert merged.data == {"regions": {"hp": [0, 0, 1, 1]}, "entity_types": ["boss"]}
    assert store.get("g") == merged


def test_merge_is_shallow(conn: sqlite3.Connection) -> None:
    store = ProfileStore(conn)
    store.merge_data("g", {"regions": {"hp": 1, "mana": 2}})
    assert store.merge_data("g", {"regions": {"hp": 3}}).data == {"regions": {"hp": 3}}


def test_merge_leaves_no_transaction_open(conn: sqlite3.Connection) -> None:
    ProfileStore(conn).merge_data("g", {"a": 1})
    assert not conn.in_transaction


def test_merge_rolls_back_when_data_cannot_be_encoded(conn: sqlite3.Connection) -> None:
    store = ProfileStore(conn)
    store.merge_data("g", {"a": 1})
    with pytest.raises(TypeError):
        store.merge_data("g", {"b": object()})
    assert not conn.in_transaction
    assert store.get("g").data == {"a": 1}


def test_brief_and_data_do_not_overwrite_each_other(conn: sqlite3.Connection) -> None:
    store = ProfileStore(conn)
    store.set_brief("g", "A sandbox game.")
    store.merge_data("g", {"regions": {}})
    assert store.get("g").brief == "A sandbox game."
    store.set_brief("g", "A 2D sandbox game.")
    assert store.get("g") == GameProfile("g", "A 2D sandbox game.", {"regions": {}})


def test_profiles_are_separate_per_game(conn: sqlite3.Connection) -> None:
    store = ProfileStore(conn)
    store.merge_data("a", {"x": 1})
    assert store.get("b").data == {}


def test_writes_stamp_the_injected_clock(conn: sqlite3.Connection) -> None:
    ProfileStore(conn, clock=lambda: 123.0).set_brief("g", "brief")
    assert conn.execute("SELECT updated_at FROM profile").fetchone()[0] == 123.0


def test_player_values_round_trip_as_json(conn: sqlite3.Connection) -> None:
    store = PlayerStore(conn)
    store.set("muted", {"until": 5, "tags": ["a"]})
    assert store.get("muted") == {"until": 5, "tags": ["a"]}
    store.set("muted", False)
    assert store.get("muted") is False


def test_player_get_returns_default_for_missing_keys(conn: sqlite3.Connection) -> None:
    assert PlayerStore(conn).get("missing") is None
    assert PlayerStore(conn).get("missing", 7) == 7


def test_settings_round_trip(conn: sqlite3.Connection) -> None:
    store = PlayerStore(conn)
    store.save_settings(SampleSettings(proactive=False, personality="dry"))
    assert store.load_settings(SampleSettings) == SampleSettings(proactive=False, personality="dry")


def test_missing_settings_use_defaults_without_warning(
    conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        assert PlayerStore(conn).load_settings(SampleSettings) == SampleSettings()
    assert caplog.records == []


def test_invalid_settings_fall_back_to_defaults_with_a_warning(
    conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    store = PlayerStore(conn)
    store.set("settings", {"proactive": "not a boolean"})
    with caplog.at_level(logging.WARNING):
        assert store.load_settings(SampleSettings) == SampleSettings()
    assert "invalid" in caplog.text
