"""Token-free memory maintenance. Run only while the brain is stopped.

The port reservation rejects a running brain and prevents it starting during a write.
Imports deliberately exclude the application, providers, capture and voice.
"""

import json
import logging
import socket
import sqlite3
import sys
import time
from pathlib import Path

from brain.config import WS_HOST, Settings
from brain.memory.admin_notes import change_note, list_notes
from brain.memory.browse import _fact
from brain.memory.db import connect
from brain.memory.facts import FactStore
from brain.memory.sample_data import seed_samples
from shared.protocol.admin import AdminFact, MemoryAdminRequest, MemoryAdminResult


def administer(
    conn: sqlite3.Connection, path: Path, request: MemoryAdminRequest
) -> MemoryAdminResult:
    backup = None
    store = FactStore(conn)
    if request.operation in {"edit_note", "delete_note"}:
        change_note(conn, request)
    elif request.operation == "seed":
        seed_samples(conn)
    elif request.operation == "clear":
        if request.confirmation != "CLEAR":
            raise ValueError("Type CLEAR to erase all saved conversations and facts")
        backup = str(path.with_name(f"{path.name}.backup-{time.time_ns()}").resolve())
        with sqlite3.connect(backup) as target:
            conn.backup(target)
        # Derived vectors must disappear too, or reused row IDs could recall old text.
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'fact_vectors'").fetchone():
            from brain.memory.vectors import load_extension

            load_extension(conn)
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            for table in ("fact_vectors", "note_vectors", "vector_model"):
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            for table in ("questions", "facts", "session_notes", "events", "sessions"):
                conn.execute(f"DELETE FROM {table}")
            conn.execute("DELETE FROM player WHERE key != 'settings'")
    elif request.operation in {"remember", "forget"}:
        game, subject, attribute = request.game, request.subject, request.attribute
        if request.fact_id is not None:
            row = conn.execute("SELECT * FROM facts WHERE id = ?", (request.fact_id,)).fetchone()
            if row is None or row["valid_to"] is not None:
                raise ValueError("That fact is no longer current; refresh memory")
            game, subject, attribute = row["game"], row["subject"], row["attribute"]
        if request.operation == "forget":
            if request.fact_id is None:
                raise ValueError("Choose the fact to forget")
            store.forget(game, subject, attribute)
        else:
            store.remember(game, subject, attribute, request.value, "player", 1.0)
    rows = conn.execute(
        "SELECT * FROM facts WHERE valid_to IS NULL ORDER BY id DESC LIMIT 200"
    ).fetchall()

    def count(table: str) -> int:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    return MemoryAdminResult(
        facts=[AdminFact(**_fact(row).model_dump(), game=row["game"]) for row in rows],
        note_items=list_notes(conn),
        total_facts=conn.execute("SELECT count(*) FROM facts WHERE valid_to IS NULL").fetchone()[0],
        notes=count("session_notes"),
        events=count("events"),
        questions=count("questions"),
        database=str(path.resolve()),
        backup=backup,
    )


def main() -> None:
    settings = Settings()
    request = MemoryAdminRequest.model_validate_json(sys.stdin.read())
    with socket.socket() as guard:
        if sys.platform == "win32":
            guard.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            guard.bind((WS_HOST, settings.brain_port))
            guard.listen(1)
        except OSError as exc:
            raise RuntimeError("Stop the running brain before managing memory") from exc
        conn = connect(settings.db_path)
        try:
            result = administer(conn, settings.db_path, request)
            sys.stdout.write(result.model_dump_json())
        finally:
            conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.getLogger(__name__).exception("Memory maintenance failed")
        sys.stderr.write(json.dumps({"error": str(exc)}))
        sys.exit(1)
