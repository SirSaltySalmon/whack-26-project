"""Parses the note writer's JSON reply. It's model output, so every field is checked and one bad
item never costs the rest of the note."""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_CONFIDENCE = 0.7
MAX_UNKNOWNS_PER_NOTE = 2


@dataclass(frozen=True)
class DraftFact:
    subject: str
    attribute: str
    value: str
    confidence: float = DEFAULT_CONFIDENCE


@dataclass(frozen=True)
class DraftUnknown:
    subject: str
    attribute: str
    question: str


@dataclass(frozen=True)
class DraftAnswer:
    question_id: int
    answer: str
    # The right value after a "No", so the wrong guess is replaced rather than just closed.
    correction: str | None = None


@dataclass(frozen=True)
class NoteDraft:
    body: str
    facts: list[DraftFact] = field(default_factory=list)
    unknowns: list[DraftUnknown] = field(default_factory=list)
    answers: list[DraftAnswer] = field(default_factory=list)


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


def _confidence(raw: object) -> float:
    # bool is an int in Python, but true isn't a meaningful confidence.
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return DEFAULT_CONFIDENCE
    return min(1.0, max(0.0, float(raw)))


def _texts(raw: dict[str, Any], keys: tuple[str, ...]) -> list[str] | None:
    parts = [raw.get(key) for key in keys]
    if not all(isinstance(part, str) and part.strip() for part in parts):
        return None
    return [str(part).strip() for part in parts]


def _parse_fact(raw: object) -> DraftFact | None:
    if not isinstance(raw, dict):
        return None
    parts = _texts(raw, ("subject", "attribute", "value"))
    if parts is None:
        return None
    subject, attribute, value = parts
    return DraftFact(subject, attribute, value, _confidence(raw.get("confidence")))


def _parse_unknown(raw: object) -> DraftUnknown | None:
    if not isinstance(raw, dict):
        return None
    parts = _texts(raw, ("subject", "attribute", "question"))
    if parts is None:
        return None
    subject, attribute, question = parts
    return DraftUnknown(subject, attribute, question)


def _parse_answer(raw: object) -> DraftAnswer | None:
    if not isinstance(raw, dict):
        return None
    question_id, answer = raw.get("question_id"), raw.get("answer")
    if isinstance(question_id, bool) or not isinstance(question_id, int):
        return None
    if not isinstance(answer, str) or not answer.strip():
        return None
    correction = raw.get("correction")
    # A missing or unusable correction still leaves a usable answer.
    cleaned = correction.strip() if isinstance(correction, str) else ""
    return DraftAnswer(question_id, answer.strip(), cleaned or None)


def _parse_list(reply: dict[str, Any], key: str, parse: Callable[[object], Any]) -> list[Any]:
    raw_items = reply.get(key, [])
    if not isinstance(raw_items, list):
        log.warning("Note reply's %s aren't a list; ignoring them: %.200s", key, raw_items)
        return []
    parsed = [(raw, parse(raw)) for raw in raw_items]
    for raw, item in parsed:
        if item is None:
            log.warning("Dropped malformed item in %s: %.200s", key, raw)
    return [item for _, item in parsed if item is not None]


def parse_note_reply(text: str) -> NoteDraft:
    """Raises ValueError when there's no usable note. One bad fact doesn't cost the whole note."""
    try:
        reply: Any = json.loads(_strip_fence(text))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Note reply isn't JSON: {text[:200]!r}") from exc
    if not isinstance(reply, dict):
        raise ValueError(f"Note reply isn't a JSON object: {text[:200]!r}")
    body = reply.get("body")
    if not isinstance(body, str) or not body.strip():
        raise ValueError(f"Note reply has no body: {text[:200]!r}")

    return NoteDraft(
        body.strip(),
        _parse_list(reply, "facts", _parse_fact),
        _parse_list(reply, "unknowns", _parse_unknown)[:MAX_UNKNOWNS_PER_NOTE],
        _parse_list(reply, "answers", _parse_answer),
    )
