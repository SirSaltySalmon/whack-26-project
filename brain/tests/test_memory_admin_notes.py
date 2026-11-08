from pathlib import Path

import pytest

from brain.memory import vectors
from brain.memory.admin import administer
from brain.memory.db import connect
from brain.memory.reader import MemoryReader
from brain.memory.sample_data import SAMPLE_GAME
from shared.protocol.admin import MemoryAdminRequest
from shared.protocol.control import ContextPreview, MemoryQuery


def test_note_edit_and_delete_update_search_recall_and_vectors(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    conn = connect(path)
    reader = MemoryReader(path)
    try:
        seeded = administer(conn, path, MemoryAdminRequest(operation="seed"))
        note = seeded.note_items[0]
        vectors.prepare(conn, "test", 3)
        vectors.store(conn, [vectors.Pending("note", note.id, note.body)], [[1, 0, 0]])
        old_word = "spare" if "spare" in note.body else "wooden"
        assert reader.answer(
            MemoryQuery(request_id="before", game=SAMPLE_GAME, text=old_word)
        ).notes
        changed = administer(
            conn,
            path,
            MemoryAdminRequest(
                operation="edit_note",
                note_id=note.id,
                body="[SAMPLE] Gather sapphires tomorrow.",
                expected_body=note.body,
            ),
        )
        saved = next(n for n in changed.note_items if n.id == note.id)
        assert saved.body == "[SAMPLE] Gather sapphires tomorrow."
        assert saved.created_at == note.created_at and saved.session_id == note.session_id
        assert not conn.execute(
            "SELECT 1 FROM note_vectors WHERE note_id = ?", (note.id,)
        ).fetchall()
        assert not reader.answer(
            MemoryQuery(request_id="old", game=SAMPLE_GAME, text=old_word)
        ).notes
        assert reader.answer(
            MemoryQuery(request_id="new", game=SAMPLE_GAME, text="sapphires")
        ).notes
        assert (
            "sapphires"
            in reader.answer(
                ContextPreview(request_id="context", game=SAMPLE_GAME, text="sapphires")
            ).context
        )
        vectors.store(conn, [vectors.Pending("note", note.id, saved.body)], [[1, 0, 0]])
        deleted = administer(
            conn,
            path,
            MemoryAdminRequest(
                operation="delete_note",
                note_id=note.id,
                expected_body=saved.body,
            ),
        )
        assert all(n.id != note.id for n in deleted.note_items)
        assert deleted.notes == seeded.notes - 1
        assert len(deleted.facts) == len(seeded.facts)
        assert not reader.answer(
            MemoryQuery(request_id="gone", game=SAMPLE_GAME, text="sapphires")
        ).notes
        assert (
            "sapphires"
            not in reader.answer(
                ContextPreview(request_id="context-gone", game=SAMPLE_GAME, text="sapphires")
            ).context
        )
        assert not conn.execute(
            "SELECT 1 FROM note_vectors WHERE note_id = ?", (note.id,)
        ).fetchall()
    finally:
        reader.close()
        conn.close()


def test_samples_are_separate_labelled_and_not_duplicated(tmp_path: Path) -> None:
    conn = connect(tmp_path / "memory.db")
    try:
        first = administer(conn, tmp_path / "memory.db", MemoryAdminRequest(operation="seed"))
        second = administer(conn, tmp_path / "memory.db", MemoryAdminRequest(operation="seed"))
        assert first.notes == second.notes == 2
        assert first.total_facts == second.total_facts == 2
        assert all(n.game == SAMPLE_GAME and "SAMPLE" in n.body for n in first.note_items)
        assert all(f.game == SAMPLE_GAME and "sample" in f.value for f in first.facts)
        assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
    finally:
        conn.close()


def test_note_changes_refuse_stale_missing_and_empty_inputs(tmp_path: Path) -> None:
    conn = connect(tmp_path / "memory.db")
    try:
        note = administer(
            conn, tmp_path / "memory.db", MemoryAdminRequest(operation="seed")
        ).note_items[0]
        for operation in ("edit_note", "delete_note"):
            with pytest.raises(ValueError, match="changed since"):
                administer(
                    conn,
                    tmp_path / "memory.db",
                    MemoryAdminRequest(
                        operation=operation,
                        note_id=note.id,
                        body="Replacement",
                        expected_body="stale",
                    ),
                )
        with pytest.raises(ValueError, match="cannot be empty"):
            administer(
                conn,
                tmp_path / "memory.db",
                MemoryAdminRequest(operation="edit_note", note_id=note.id, body=" "),
            )
        with pytest.raises(ValueError, match="no longer exists"):
            administer(
                conn,
                tmp_path / "memory.db",
                MemoryAdminRequest(operation="delete_note", note_id=9999),
            )
        assert (
            conn.execute("SELECT body FROM session_notes WHERE id = ?", (note.id,)).fetchone()[0]
            == note.body
        )
    finally:
        conn.close()
