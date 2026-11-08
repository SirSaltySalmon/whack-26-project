"""`python -m brain --memory`: answers the Control Center's memory requests with the partner off.

Reads one JSON request per line on stdin and writes one reply per line on stdout, so the player can
browse memory, and pick which game's, without capture, voice or any model starting. The database
is opened read-only: it can run beside a brain that's writing, and it never changes memory.
"""

import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import TextIO

from pydantic import ValidationError

from brain.memory.browse import browse, games, preview_context
from brain.memory.db import connect, connect_readonly
from shared.protocol import ControlReply, ControlRequestAdapter
from shared.protocol.control import (
    ContextPreview,
    ControlError,
    MemoryContext,
    MemoryGames,
    MemoryListGames,
    MemoryQuery,
    MemoryResults,
)

log = logging.getLogger(__name__)


class MemoryUnavailable(Exception):
    """Memory can't be read at all, with a reason the player can act on."""


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


class MemoryReader:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: sqlite3.Connection | None = None
        self._empty: sqlite3.Connection | None = None

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            # Checked on every request while there's no file, so memory the partner writes later
            # shows up without restarting the reader.
            if not self._path.exists():
                self._empty = self._empty or connect(":memory:")
                return self._empty
            try:
                self._conn = connect_readonly(self._path)
            except (RuntimeError, sqlite3.Error) as exc:
                raise MemoryUnavailable(f"Couldn't open {self._path}: {exc}") from exc
        return self._conn

    @staticmethod
    def _latest(conn: sqlite3.Connection) -> str | None:
        found = games(conn)
        return found[0].title if found else None

    def answer(self, request: object) -> ControlReply:
        conn = self._connection()
        started = time.perf_counter()
        match request:
            case MemoryListGames():
                return MemoryGames(
                    request_id=request.request_id,
                    games=games(conn),
                    current=self._latest(conn),
                    live=False,
                )
            case MemoryQuery():
                game = request.game if request.game is not None else self._latest(conn) or ""
                found = browse(conn, game, request.text, request.include_history, request.limit)
                return MemoryResults(
                    request_id=request.request_id,
                    facts=found.facts,
                    questions=found.questions,
                    notes=found.notes,
                    elapsed_ms=_elapsed_ms(started),
                )
            case ContextPreview():
                game = request.game if request.game is not None else self._latest(conn) or ""
                return MemoryContext(
                    request_id=request.request_id,
                    context=preview_context(conn, game, request.text),
                    elapsed_ms=_elapsed_ms(started),
                )
        return ControlError(
            request_id=getattr(request, "request_id", None),
            message="Only memory can be read while the partner is off",
        )

    def close(self) -> None:
        for conn in (self._conn, self._empty):
            if conn is not None:
                conn.close()


def reply_to(reader: MemoryReader, line: str) -> ControlReply:
    try:
        request = ControlRequestAdapter.validate_json(line)
    except ValidationError:
        log.warning("Rejected invalid memory request: %.200s", line)
        return ControlError(message="Invalid request")
    request_id = getattr(request, "request_id", None)
    try:
        return reader.answer(request)
    except MemoryUnavailable as exc:
        log.error("%s", exc)
        return ControlError(request_id=request_id, message=str(exc))
    except Exception as exc:
        log.exception("Memory request %s failed", request.type)
        return ControlError(request_id=request_id, message=type(exc).__name__)


def serve(reader: MemoryReader, lines: TextIO, out: TextIO) -> None:
    """Until stdin closes, which is how the Control Center stops it."""
    for line in lines:
        if not line.strip():
            continue
        out.write(reply_to(reader, line).model_dump_json() + "\n")
        out.flush()


def run_reader(path: Path) -> None:
    # Memory holds text in any language, and the Windows console encoding would mangle it.
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    log.info("Reading memory from %s", path)
    reader = MemoryReader(path)
    try:
        serve(reader, sys.stdin, sys.stdout)
    finally:
        reader.close()
