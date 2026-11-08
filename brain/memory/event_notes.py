"""What tool calls and game events read as in the conversation.

A note is data on the player's side of the conversation, never something they said. Tool notes
come from brain/agent/tool_notes.py and read as what "you", the partner, did. Game events come
from the observer's tracker or from the readers learned for this game. Their names are generic or
come from the learned profile, so an event not named below is described from its data alone,
never by knowing the game.

A reader watching a changing number can fire every few seconds, so a run of the same event with
nothing said in between becomes one note (brain/memory/conversation.py also keeps only the newest
few runs of each event).
"""

from dataclasses import dataclass, replace
from typing import Any

from brain.memory.sessions import TOOL_PREFIX, TURN_PREFIX

NOTE_CHARS = 160
_LIST_CHARS = 60
_ELLIPSIS = "…"


@dataclass(frozen=True)
class NoteRun:
    """One event, or a run of the same game event, waiting to become a note."""

    name: str
    first: dict[str, Any]
    last: dict[str, Any]
    # The newest event's, so the note sits where the run ended.
    ts: float
    count: int = 1

    @property
    def is_tool(self) -> bool:
        return self.name.startswith(TOOL_PREFIX)

    def joins(self, name: str) -> bool:
        """A repeat of this game event. Tool notes never join: two looks found different things."""
        return not self.is_tool and name == self.name

    def extended(self, data: dict[str, Any], ts: float) -> "NoteRun":
        return replace(self, last=data, ts=ts, count=self.count + 1)


def _clean(value: object) -> str:
    # str.split() also breaks on Unicode line separators, so a note stays one line.
    return " ".join(str(value).split())


def _shorten(text: str, limit: int) -> str:
    text = _clean(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip(" ,;:") + _ELLIPSIS


def _percent(data: dict[str, Any]) -> str:
    percent = data.get("percent")
    return f" ({percent}%)" if isinstance(percent, int | float) else ""


def _threats(data: dict[str, Any]) -> str:
    threats = data.get("threats")
    if not isinstance(threats, list) or not threats:
        return ""
    return ": " + _shorten(", ".join(_clean(threat) for threat in threats), _LIST_CHARS)


def _value(data: dict[str, Any]) -> str:
    shown = data.get("display")
    return _clean(shown if shown not in (None, "") else data.get("value", ""))


def _generic(run: NoteRun) -> str:
    """For events named by a learned profile, such as a reader's "mana_low" or "biome_changed"."""
    what = _clean(run.name.replace("_", " "))
    if "from" in run.first:
        line = f"{what}: {_clean(run.first['from'])} to {_value(run.last)}"
        return line + (f" ({run.count} changes)" if run.count > 1 else "")
    value = _value(run.last)
    percent = _percent(run.last) if "%" not in value else ""
    line = f"{what}: {value}{percent}" if value else what
    return line + (f" ({run.count} times)" if run.count > 1 else "")


def _game_line(run: NoteRun) -> str:
    level = run.last.get("level")
    match run.name:
        case "danger_started":
            line = f"danger started{f' ({_clean(level)})' if level else ''}{_threats(run.last)}"
        case "danger_high":
            line = f"danger rose to high{_threats(run.last)}"
        case "danger_ended":
            line = "danger ended"
        case "health_low":
            line = f"health low{_percent(run.last)}"
        case "player_died":
            line = "the player died"
        case _:
            return _generic(run)
    return line + (f" ({run.count} times)" if run.count > 1 else "")


def note_text(run: NoteRun) -> str | None:
    """The note's line, or None to leave it out."""
    if run.name.startswith(TURN_PREFIX):
        return None
    if run.is_tool:
        text = _clean(run.last.get("text") or "")
        return _shorten(f"you {text}", NOTE_CHARS) if text else None
    return _shorten(f"game: {_game_line(run)}", NOTE_CHARS)
