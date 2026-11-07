"""Pure helpers for FactStore: cleaned input, row mapping and question wording."""

import json
import sqlite3
from dataclasses import fields
from typing import Any, NamedTuple

from brain.memory.models import Fact, Question, Source

YES_NO = ["Yes", "No"]
# The player is the one being spoken to, so these subjects read as "your X" in a question.
_PLAYER_SUBJECTS = frozenset({"player", "me", "you", "i"})


class NewFact(NamedTuple):
    """Validated and cleaned. Field order matches the INSERT in FactStore."""

    game: str | None
    session_id: int | None
    subject: str
    attribute: str
    value: str
    source: Source
    confidence: float


def clean(text: str, name: str) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        raise ValueError(f"Fact {name} is empty")
    return cleaned


def same_value(left: str, right: str) -> bool:
    return left.strip().casefold() == right.strip().casefold()


def is_yes_no(question: Question) -> bool:
    # A dispute between the literal values "Yes" and "No" has the same options but links two or
    # more facts, and must be settled as a conflict rather than by confirming one fact.
    return question.options == YES_NO and len(question.fact_ids) == 1


def possessive(subject: str, attribute: str) -> str:
    if subject.casefold() in _PLAYER_SUBJECTS:
        return f"your {attribute}"
    return f"{subject}'s {attribute}"


def conflict_text(subject: str, attribute: str, options: list[str]) -> str:
    choices = f"{', '.join(options[:-1])}, or {options[-1]}"
    return f"Is {possessive(subject, attribute)} {choices}?"


def _record_fields(record: type[Any], row: sqlite3.Row) -> dict[str, Any]:
    return {field.name: row[field.name] for field in fields(record)}


def to_fact(row: sqlite3.Row) -> Fact:
    return Fact(**{**_record_fields(Fact, row), "tentative": bool(row["tentative"])})


def to_question(row: sqlite3.Row) -> Question:
    values = _record_fields(Question, row)
    return Question(
        **{**values, "options": json.loads(row["options"]), "fact_ids": json.loads(row["fact_ids"])}
    )
