"""SQLite connection, and the one worker thread that uses it from async code."""

import asyncio
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypeVar

SCHEMA = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 2

T = TypeVar("T")


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    # Created on the caller's thread but used on Database's worker, so the check must be off.
    # Database's single worker is what actually keeps access serialized.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    _check_version(conn, path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return conn


def connect_readonly(path: Path) -> sqlite3.Connection:
    """For reading memory with the partner off, or beside one that's writing: WAL lets both run.
    Never creates the file or touches the schema. The file must exist."""
    uri = f"{Path(path).resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _check_version(conn, path)
    return conn


def _check_version(conn: sqlite3.Connection, path: Path | str) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    has_tables = conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone() is not None
    # CREATE IF NOT EXISTS would keep old tables and fail later in confusing ways. We don't delete
    # the file automatically because it holds the player's memory.
    if has_tables and version != SCHEMA_VERSION:
        conn.close()
        raise RuntimeError(
            f"{path} uses memory schema {version}, expected {SCHEMA_VERSION}. Delete it or point"
            " db_path somewhere else."
        )


class Database:
    """Runs sync store calls off the event loop. One worker means calls run in submission order."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory-db")

    async def run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fn, self.conn)

    def close(self) -> None:
        self._executor.shutdown(wait=True)
        self.conn.close()
