"""One-way export to an Obsidian vault, for reading. SQLite stays the source of truth."""

import hashlib
import json
import logging
import os
import re
import sqlite3
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from brain.memory.context import fact_from_row, format_fact
from brain.memory.db import Database
from brain.memory.models import Fact, LoggedEvent, Note, Session

log = logging.getLogger(__name__)

# Windows treats these as devices whatever the extension, so `CON.md` isn't a normal file either.
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
# Path and Windows characters, plus the ones that would break an Obsidian [[wikilink]].
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\[\]#^\x00-\x1f\x7f]')
_MAX_NAME_CHARS = 80


def safe_name(title: str) -> str:
    """Makes a game title into one safe folder name. It can never name a path segment like `..`."""
    words = _UNSAFE_CHARS.sub(" ", title).split()
    cleaned = " ".join(word for word in words if word.strip("."))
    cleaned = cleaned[:_MAX_NAME_CHARS].strip(" .") or "Game"
    if cleaned.split(".")[0].strip().upper() in _RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    if cleaned == title:
        return cleaned
    # Two different titles can clean to the same name, and they mustn't share a folder.
    digest = hashlib.sha256(title.encode("utf-8", "surrogatepass")).hexdigest()[:6]
    return f"{cleaned} {digest}"


def _local(ts: float, fmt: str = "%Y-%m-%d %H:%M") -> str:
    try:
        return datetime.fromtimestamp(ts).strftime(fmt)
    except (OSError, OverflowError, ValueError):
        # One bad timestamp shouldn't cost the player the rest of the export.
        return "unknown date"


def _yaml(value: str) -> str:
    # JSON strings are valid YAML, and this escapes the quotes, colons and newlines that matter.
    return json.dumps(value, ensure_ascii=False)


def session_stem(session: Session) -> str:
    return f"{_local(session.started_at, '%Y-%m-%d')} Session {session.id}"


def render_index(game: str, folder: str, brief: str, sessions: Sequence[Session]) -> str:
    # Links use the full vault path because every game folder has its own Facts note.
    lines = [f"# {' '.join(game.split())}", ""]
    if brief.strip():
        lines += [brief.strip(), ""]
    lines += [f"- [[{folder}/Facts|Facts]]", "", "## Sessions", ""]
    for session in sessions:
        stem = session_stem(session)
        lines.append(f"- [[{folder}/Sessions/{stem}|{stem}]]")
    return "\n".join(lines).rstrip() + "\n"


def render_facts(current: Sequence[Fact], closed: Sequence[Fact]) -> str:
    groups: dict[str, list[Fact]] = {}
    for fact in current:
        groups.setdefault(fact.subject.casefold(), []).append(fact)

    lines = ["# Facts", ""]
    for key in sorted(groups):
        lines += [f"## {' '.join(groups[key][0].subject.split())}", ""]
        for fact in groups[key]:
            mark = ", **Unconfirmed**" if fact.tentative else ""
            value = " ".join(fact.value.split())
            attribute = " ".join(fact.attribute.split())
            lines.append(
                f"- {attribute}: {value} ({fact.source}, confidence {fact.confidence:.2f}{mark})"
            )
        lines.append("")
    if closed:
        lines += ["## History", ""]
        for fact in closed:
            ended = _local(fact.valid_to) if fact.valid_to is not None else "unknown date"
            lines.append(f"- {format_fact(fact)}, from {_local(fact.valid_from)} to {ended}")
    return "\n".join(lines).rstrip() + "\n"


def render_session(
    game: str, folder: str, session: Session, notes: Sequence[Note], moments: Sequence[LoggedEvent]
) -> str:
    ended = _yaml(_local(session.ended_at)) if session.ended_at is not None else "null"
    lines = [
        "---",
        f"game: {_yaml(game)}",
        f"session: {session.id}",
        f"started: {_yaml(_local(session.started_at))}",
        f"ended: {ended}",
        "---",
        "",
        f"# {session_stem(session)}",
        "",
        f"Part of [[{folder}/Index|{' '.join(game.split())}]]",
        "",
    ]
    for note in (n for n in notes if n.kind == "recap"):
        lines += ["## Recap", "", note.body.strip(), ""]
    rolling = [n for n in notes if n.kind == "rolling"]
    if rolling:
        lines += ["## Notes", ""]
        for note in rolling:
            lines += [f"### {_local(note.created_at, '%H:%M:%S')}", "", note.body.strip(), ""]
    if moments:
        lines += ["## Moments", ""]
        for event in moments:
            lines.append(f"- {_local(event.ts, '%H:%M:%S')} {' '.join(event.name.split())}")
    return "\n".join(lines).rstrip() + "\n"


def _write_if_changed(path: Path, content: str, root: Path) -> bool:
    # safe_name should already guarantee this. A bug here would write into the player's files.
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"Refusing to export outside the vault: {path}")
    data = content.encode("utf-8")
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replacing atomically means Obsidian never sees a half-written note. The dot keeps the
    # temporary file out of its file list.
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    return True


def _sessions(conn: sqlite3.Connection, game: str) -> list[Session]:
    rows = conn.execute(
        "SELECT id, game, started_at, ended_at FROM sessions WHERE game = ? ORDER BY id DESC",
        (game,),
    ).fetchall()
    return [Session(row["id"], row["game"], row["started_at"], row["ended_at"]) for row in rows]


def _load_page(conn: sqlite3.Connection, session_id: int) -> tuple[list[Note], list[LoggedEvent]]:
    notes = conn.execute(
        "SELECT id, session_id, kind, body, from_ts, to_ts, created_at FROM session_notes"
        " WHERE session_id = ? ORDER BY created_at, id",
        (session_id,),
    ).fetchall()
    events = conn.execute(
        "SELECT id, session_id, ts, name FROM events"
        " WHERE session_id = ? AND name NOT LIKE 'turn.%' ORDER BY ts, id",
        (session_id,),
    ).fetchall()
    return [Note(**dict(note)) for note in notes], [LoggedEvent(**dict(event)) for event in events]


def export_vault(
    conn: sqlite3.Connection, vault_dir: Path, game: str, live_session: int | None = None
) -> list[Path]:
    """Writes one game's notes and returns the files that changed. It never deletes anything.

    With `live_session`, only that session's page is rebuilt, and other pages are written only
    when missing, because notes and moments are only ever added to the session being played.
    Rebuilding every page took seconds once a few hundred sessions had built up, and it holds up
    the memory worker that the voice path waits on. Delete a page to have it rebuilt.

    Blocking file and database work, so call it through `Database.run`. Raises OSError when the
    vault can't be written, and the caller decides how to report that.
    """
    root = vault_dir.resolve()
    folder = safe_name(game)
    # Returned paths stay under vault_dir as the caller wrote it. Only the safety check resolves.
    base = vault_dir / folder
    sessions_dir = base / "Sessions"

    profile = conn.execute("SELECT brief FROM profile WHERE game = ?", (game,)).fetchone()
    sessions = _sessions(conn, game)
    facts = [
        fact_from_row(row)
        for row in conn.execute(
            "SELECT * FROM facts WHERE game = ? OR game IS NULL ORDER BY valid_from, id", (game,)
        ).fetchall()
    ]
    current = [fact for fact in facts if fact.valid_to is None]
    closed = [fact for fact in reversed(facts) if fact.valid_to is not None]

    brief = profile["brief"] if profile else ""
    documents = {
        base / "Index.md": render_index(game, folder, brief, sessions),
        base / "Facts.md": render_facts(current, closed),
    }
    # One directory listing rather than a check per session, because there can be hundreds.
    incremental = live_session is not None and sessions_dir.is_dir()
    existing = set(os.listdir(sessions_dir)) if incremental else set()
    for session in sessions:
        name = f"{session_stem(session)}.md"
        if session.id != live_session and name in existing:
            continue
        notes, moments = _load_page(conn, session.id)
        documents[sessions_dir / name] = render_session(game, folder, session, notes, moments)

    written = [path for path, text in documents.items() if _write_if_changed(path, text, root)]
    log.info("Vault export for %r: %d of %d files changed", game, len(written), len(documents))
    return written


async def export_quietly(
    database: Database, vault_dir: Path, game: str, live_session: int | None = None
) -> None:
    """Logs a failure instead of raising, because the vault is only a view of SQLite."""
    try:
        await database.run(lambda conn: export_vault(conn, vault_dir, game, live_session))
    except OSError:
        log.exception("Vault export to %s failed", vault_dir)
