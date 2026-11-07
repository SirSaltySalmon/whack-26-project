"""The learned game profile and the player's settings. Sync: call through Database.run."""

import json
import logging
import sqlite3
import time
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from brain.memory.models import GameProfile

log = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

_SETTINGS_KEY = "settings"


class ProfileStore:
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time) -> None:
        self._conn = conn
        self._clock = clock

    def get(self, game: str) -> GameProfile:
        row = self._conn.execute(
            "SELECT brief, data FROM profile WHERE game = ?", (game,)
        ).fetchone()
        if row is None:
            # A game we haven't learned yet is normal, so callers shouldn't need a None check.
            return GameProfile(game=game)
        return GameProfile(game=game, brief=row["brief"], data=json.loads(row["data"]))

    def set_brief(self, game: str, brief: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO profile (game, brief, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT (game) DO UPDATE SET"
                " brief = excluded.brief, updated_at = excluded.updated_at",
                (game, brief, self._clock()),
            )

    def merge_data(self, game: str, updates: Mapping[str, Any]) -> GameProfile:
        """Merges top-level keys, so writing readers can't lose learned regions."""
        with self._conn:
            # sqlite3 only opens a transaction before a write, which would leave the read below
            # outside it. json_patch isn't an option: it merges recursively and null deletes keys.
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT brief, data FROM profile WHERE game = ?", (game,)
            ).fetchone()
            brief = row["brief"] if row is not None else ""
            data = json.loads(row["data"]) if row is not None else {}
            data.update(updates)
            self._conn.execute(
                "INSERT INTO profile (game, brief, data, updated_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT (game) DO UPDATE SET"
                " data = excluded.data, updated_at = excluded.updated_at",
                (game, brief, json.dumps(data), self._clock()),
            )
        return GameProfile(game=game, brief=brief, data=data)


class PlayerStore:
    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], float] = time.time) -> None:
        self._conn = conn
        # The player table has no timestamp yet. Kept so every store is built the same way.
        self._clock = clock

    def get(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute("SELECT value FROM player WHERE key = ?", (key,)).fetchone()
        return default if row is None else json.loads(row["value"])

    def set(self, key: str, value: Any) -> None:
        encoded = json.dumps(value)
        with self._conn:
            self._conn.execute(
                "INSERT INTO player (key, value) VALUES (?, ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, encoded),
            )

    def load_settings(self, model: type[ModelT]) -> ModelT:
        # The model is passed in rather than imported, so memory doesn't depend on the protocol.
        stored = self.get(_SETTINGS_KEY)
        if stored is None:
            return model()
        try:
            return model.model_validate(stored)
        except ValidationError:
            # A protocol field change can invalidate saved settings. Losing them is much better
            # than the partner failing to start.
            log.warning("Stored settings are invalid; using defaults", exc_info=True)
            return model()

    def save_settings(self, settings: BaseModel) -> None:
        self.set(_SETTINGS_KEY, settings.model_dump(mode="json"))
