"""Personalities are data, so adding or changing one never touches the code."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

_DEFAULT_PATH = Path(__file__).with_name("personalities.json")

LineKind = Literal["looking", "done", "unavailable", "danger", "danger_high", "died", "low_health"]


class Personality(BaseModel):
    tone: str
    lines: dict[LineKind, list[str]]


class PersonalityBook(BaseModel):
    default: str
    personalities: dict[str, Personality]
    # Which game events have a fixed line, by GameEvent name.
    event_lines: dict[str, LineKind] = Field(default_factory=dict)

    @property
    def names(self) -> list[str]:
        return list(self.personalities)

    def _get(self, name: str) -> Personality:
        # A setting saved before a personality was renamed shouldn't stop the partner talking.
        return self.personalities.get(name) or self.personalities[self.default]

    def tone(self, name: str) -> str:
        return self._get(name).tone

    def line(self, name: str, kind: LineKind, turn: int) -> str:
        """Takes a turn count rather than picking at random, so tests stay deterministic."""
        lines = self._get(name).lines[kind]
        return lines[turn % len(lines)]


def load_personalities(path: Path = _DEFAULT_PATH) -> PersonalityBook:
    return PersonalityBook.model_validate_json(path.read_text(encoding="utf-8"))
