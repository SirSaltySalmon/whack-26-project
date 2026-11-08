"""The conversation so far, as the messages every spoken reply is sent with.

The partner's own lines go back as its own messages. Before this they sat in a reference block
framed as "not part of the conversation", cut to one line, and the partner asked the same
question twice without knowing it had (docs/CONTEXT_PLAN.md).

Notes are things that happened rather than things anyone said: what the partner's tools found,
and game events. They go in on the player's side, marked as notes, since the APIs only have two
sides. brain/memory/event_notes.py says what each one reads as.
"""

import json
import logging
import sqlite3
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from brain.llm.base import ChatTurn
from brain.memory.event_notes import NoteRun, note_text
from brain.memory.sessions import TURN_PREFIX

log = logging.getLogger(__name__)

ItemKind = Literal["player", "partner", "note"]

_TURN_EVENTS: dict[str, ItemKind] = {"turn.player": "player", "turn.partner": "partner"}
# Notes read per call. Read apart from turns, so a flood of events can't push turns out.
MAX_NOTE_ROWS = 60
# The newest runs of one game event kept. Older ones are left to the session note.
RUNS_PER_EVENT = 3
_ELLIPSIS = "…"
_ROWS = "SELECT id, name, data, ts FROM events WHERE session_id = ?"


@dataclass(frozen=True)
class ConversationItem:
    kind: ItemKind
    text: str
    # Wall-clock seconds, as the events table stores them.
    ts: float


def _data(raw: str | None) -> dict[str, Any] | None:
    try:
        parsed: Any = json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _rows(
    conn: sqlite3.Connection, session_id: int, limit: int, note_limit: int
) -> list[sqlite3.Row]:
    """Both kinds, oldest first. Notes older than the oldest turn read would have no conversation
    around them, so once the turns fill their limit, notes start where they do."""
    turns = conn.execute(
        f"{_ROWS} AND name LIKE ? ORDER BY ts DESC, id DESC LIMIT ?",
        (session_id, f"{TURN_PREFIX}%", limit),
    ).fetchall()
    since = turns[-1]["ts"] if turns and len(turns) >= limit else float("-inf")
    notes = conn.execute(
        f"{_ROWS} AND name NOT LIKE ? AND ts >= ? ORDER BY ts DESC, id DESC LIMIT ?",
        (session_id, f"{TURN_PREFIX}%", since, note_limit),
    ).fetchall()
    return sorted([*turns, *notes], key=lambda row: (row["ts"], row["id"]))


def _keep_newest_runs(entries: list[ConversationItem | NoteRun]) -> list[ConversationItem | NoteRun]:
    """Only the newest few runs of each game event, so a reader firing all session can't fill the
    conversation. Tool notes are all kept: each one is something the partner did."""
    seen: Counter[str] = Counter()
    kept: list[ConversationItem | NoteRun] = []
    for entry in reversed(entries):
        if isinstance(entry, NoteRun) and not entry.is_tool:
            seen[entry.name] += 1
            if seen[entry.name] > RUNS_PER_EVENT:
                continue
        kept.append(entry)
    kept.reverse()
    return kept


def read_items(
    conn: sqlite3.Connection, session_id: int, limit: int, note_limit: int = MAX_NOTE_ROWS
) -> list[ConversationItem]:
    """This session's newest `limit` turns and the notes among them, oldest first. Never another
    session's. A run of the same game event with nothing said in between becomes one note."""
    entries: list[ConversationItem | NoteRun] = []
    for row in _rows(conn, session_id, limit, note_limit):
        data = _data(row["data"])
        kind = _TURN_EVENTS.get(row["name"])
        if kind is not None:
            text = data.get("text") if data else None
            if not isinstance(text, str) or not text.strip():
                log.warning("Skipping a turn with unusable data in session %s", session_id)
                continue
            entries.append(ConversationItem(kind, text, row["ts"]))
            continue
        previous = entries[-1] if entries else None
        if isinstance(previous, NoteRun) and previous.joins(row["name"]):
            entries[-1] = previous.extended(data or {}, row["ts"])
        else:
            entries.append(NoteRun(row["name"], data or {}, data or {}, row["ts"]))
    items: list[ConversationItem] = []
    for entry in _keep_newest_runs(entries):
        if isinstance(entry, ConversationItem):
            items.append(entry)
        elif (note := note_text(entry)) is not None:
            items.append(ConversationItem("note", note, entry.ts))
    return items


def _padded(text: str) -> str:
    return f" {' '.join(text.split()).lower()} "


def without_current(
    items: Sequence[ConversationItem], current: str | None
) -> list[ConversationItem]:
    """Leaves out the player's newest lines when they're the words being answered.

    Memory logs those words before the director reads the context, and the model gets them as its
    latest message, so listing them again would say them twice. A carried turn is the cut-off
    words and then the new ones, so each of its lines is found whole inside `current`. Notes
    logged since then are kept and skipped over.
    """
    kept = list(items)
    if not current:
        return kept
    said = _padded(current)
    index = len(kept) - 1
    while index >= 0 and kept[index].kind != "partner":
        item = kept[index]
        if item.kind == "player":
            line = _padded(item.text)
            if line.strip() and line in said:
                del kept[index]
            else:
                break
        index -= 1
    return kept


def partner_line(items: Sequence[ConversationItem]) -> str | None:
    return next((item.text for item in reversed(items) if item.kind == "partner"), None)


def session_clock(seconds: float) -> str:
    """`12:40`, or `1:02:05` past an hour. Times into the session stay the same on every call,
    unlike "40 s ago", so the cached conversation stays the same too."""
    whole = max(int(seconds), 0)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: max(limit - 1, 0)].rstrip() + _ELLIPSIS


def _turn(item: ConversationItem, started: float | None, item_chars: int) -> ChatTurn:
    text = _shorten(item.text, item_chars)
    if item.kind == "partner":
        return ChatTurn("assistant", text)
    if item.kind == "note":
        when = f", {session_clock(item.ts - started)} into the session" if started else ""
        return ChatTurn("user", f"(note{when}) {text}")
    return ChatTurn("user", text)


def history_turns(
    items: Sequence[ConversationItem],
    budget_chars: int,
    item_chars: int,
    started: float | None = None,
) -> tuple[tuple[ChatTurn, ...], int]:
    """The newest items that fit the budget, as messages, and how many older ones were left out.
    Those are left to the session note, which C7 will turn into a rolling summary. Lines from the
    same side are joined, so a note sits in the player's message next to it."""
    kept: list[ChatTurn] = []
    used = 0
    for item in reversed(items):
        turn = _turn(item, started, item_chars)
        used += len(turn.text) + 1
        if used > budget_chars:
            break
        kept.append(turn)
    kept.reverse()
    turns: list[ChatTurn] = []
    for turn in kept:
        if turns and turns[-1].role == turn.role:
            turns[-1] = ChatTurn(turn.role, f"{turns[-1].text}\n{turn.text}")
        else:
            turns.append(turn)
    return tuple(turns), len(items) - len(kept)
