import json
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from brain.memory.db import connect
from brain.memory.export import export_vault, safe_name

STARTED = 1_800_000_000.0


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = connect(":memory:")
    yield connection
    connection.close()


def add_session(conn: sqlite3.Connection, game: str = "Game", ended: float | None = None) -> int:
    cursor = conn.execute(
        "INSERT INTO sessions (game, started_at, ended_at) VALUES (?, ?, ?)",
        (game, STARTED, ended),
    )
    return int(cursor.lastrowid or 0)


def add_note(conn: sqlite3.Connection, session: int, kind: str, body: str, at: float = 1.0) -> None:
    conn.execute(
        "INSERT INTO session_notes (session_id, kind, body, from_ts, to_ts, created_at)"
        " VALUES (?, ?, ?, 0, 0, ?)",
        (session, kind, body, STARTED + at),
    )


def add_fact(
    conn: sqlite3.Connection,
    subject: str,
    attribute: str,
    value: str,
    source: str = "player",
    game: str | None = "Game",
    valid_to: float | None = None,
) -> None:
    conn.execute(
        "INSERT INTO facts (game, subject, attribute, value, source, confidence, tentative,"
        " valid_from, valid_to) VALUES (?, ?, ?, ?, ?, 0.75, ?, ?, ?)",
        (game, subject, attribute, value, source, source == "wiki", STARTED, valid_to),
    )


def session_file(session: int) -> str:
    # Built from the same local clock as the code, so this holds in any timezone.
    return f"{datetime.fromtimestamp(STARTED):%Y-%m-%d} Session {session}"


def test_writes_the_expected_layout(conn: sqlite3.Connection, tmp_path: Path) -> None:
    session = add_session(conn)
    written = export_vault(conn, tmp_path, "Game")
    assert {path.relative_to(tmp_path).as_posix() for path in written} == {
        "Game/Index.md",
        "Game/Facts.md",
        f"Game/Sessions/{session_file(session)}.md",
    }


def test_returned_paths_stay_under_the_vault_dir_as_given(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    add_session(conn)
    vault = tmp_path / "sub" / ".." / "vault"
    assert all(path.is_relative_to(vault) for path in export_vault(conn, vault, "Game"))


def test_index_links_to_facts_and_sessions_newest_first(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    conn.execute("INSERT INTO profile (game, brief, updated_at) VALUES ('Game', 'A sandbox', 1)")
    first, second = add_session(conn), add_session(conn)
    export_vault(conn, tmp_path, "Game")
    index = (tmp_path / "Game" / "Index.md").read_text(encoding="utf-8")
    assert "A sandbox" in index
    assert "[[Game/Facts|Facts]]" in index
    newest = f"[[Game/Sessions/{session_file(second)}|{session_file(second)}]]"
    oldest = f"[[Game/Sessions/{session_file(first)}|{session_file(first)}]]"
    assert index.index(newest) < index.index(oldest)


def test_facts_are_grouped_with_source_and_unconfirmed_mark(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    add_fact(conn, "Base", "location", "east")
    add_fact(conn, "base", "size", "big", source="observed")
    add_fact(conn, "Boss", "weakness", "fire", source="wiki")
    add_fact(conn, "Player", "style", "summoner", game=None)
    add_fact(conn, "Base", "location", "west", valid_to=STARTED + 60)
    add_fact(conn, "Other", "thing", "hidden", game="Other game")
    export_vault(conn, tmp_path, "Game")
    text = (tmp_path / "Game" / "Facts.md").read_text(encoding="utf-8")

    assert text.count("## Base") == 1
    assert "- location: east (player, confidence 0.75)" in text
    assert "- size: big (observed, confidence 0.75)" in text
    assert "- weakness: fire (wiki, confidence 0.75, **Unconfirmed**)" in text
    assert "summoner" in text
    assert "hidden" not in text

    current, history = text.split("## History")
    assert "west" not in current
    assert "west" in history
    assert f"{datetime.fromtimestamp(STARTED + 60):%Y-%m-%d %H:%M}" in history


def test_session_has_frontmatter_recap_first_and_moments(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    session = add_session(conn, ended=STARTED + 3600)
    add_note(conn, session, "rolling", "rolling one", at=1.0)
    add_note(conn, session, "rolling", "rolling two", at=2.0)
    add_note(conn, session, "recap", "the recap", at=3.0)
    conn.execute(
        "INSERT INTO events (session_id, ts, name, data) VALUES (?, ?, 'boss_seen', NULL)",
        (session, STARTED),
    )
    conn.execute(
        "INSERT INTO events (session_id, ts, name, data) VALUES (?, ?, 'turn.player', ?)",
        (session, STARTED, json.dumps({"text": "private chatter"})),
    )
    export_vault(conn, tmp_path, "Game")
    text = (tmp_path / "Game" / "Sessions" / f"{session_file(session)}.md").read_text(
        encoding="utf-8"
    )

    assert text.startswith('---\ngame: "Game"\n')
    assert f"session: {session}\n" in text
    assert f'started: "{datetime.fromtimestamp(STARTED):%Y-%m-%d %H:%M}"' in text
    assert f'ended: "{datetime.fromtimestamp(STARTED + 3600):%Y-%m-%d %H:%M}"' in text
    assert text.index("the recap") < text.index("rolling one") < text.index("rolling two")
    assert f"- {datetime.fromtimestamp(STARTED):%H:%M:%S} boss_seen" in text
    assert "private chatter" not in text
    assert "turn.player" not in text
    assert "[[Game/Index|Game]]" in text


def test_an_unfinished_session_has_a_null_end(conn: sqlite3.Connection, tmp_path: Path) -> None:
    session = add_session(conn)
    export_vault(conn, tmp_path, "Game")
    text = (tmp_path / "Game" / "Sessions" / f"{session_file(session)}.md").read_text(
        encoding="utf-8"
    )
    assert "ended: null\n" in text


def test_yaml_values_are_quoted_safely(conn: sqlite3.Connection, tmp_path: Path) -> None:
    game = 'Odd: "Game"\n---\nevil: true'
    session = add_session(conn, game=game)
    export_vault(conn, tmp_path, game)
    path = tmp_path / safe_name(game) / "Sessions" / f"{session_file(session)}.md"
    frontmatter = path.read_text(encoding="utf-8").split("---\n")[1]
    line = next(item for item in frontmatter.splitlines() if item.startswith("game: "))
    assert json.loads(line.removeprefix("game: ")) == game
    assert "evil: true\n" not in frontmatter.replace(line, "")


def test_unicode_is_preserved(conn: sqlite3.Connection, tmp_path: Path) -> None:
    game = "Trò chơi 星"
    session = add_session(conn, game=game)
    add_note(conn, session, "recap", "Đã thắng 🎉")
    add_fact(conn, "Căn cứ", "vị trí", "phía đông", game=game)
    export_vault(conn, tmp_path, game)
    folder = tmp_path / game
    session_text = (folder / "Sessions" / f"{session_file(session)}.md").read_text(encoding="utf-8")
    assert "Đã thắng 🎉" in session_text
    assert f'game: "{game}"' in session_text
    assert "phía đông" in (folder / "Facts.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "title",
    [
        "..\\..\\evil",
        "../../evil",
        "..",
        ".",
        "",
        "   ",
        "/etc/passwd",
        "C:\\Windows\\evil",
        "CON",
        "con.txt",
        "NUL",
        "COM1",
        "LPT9.md",
        "name|with*bad?chars",
        "trailing dots...",
        "a" * 500,
        "line\nbreak\x00null",
    ],
)
def test_hostile_titles_stay_inside_the_vault(
    conn: sqlite3.Connection, tmp_path: Path, title: str
) -> None:
    vault = tmp_path / "vault"
    add_session(conn, game=title)
    written = export_vault(conn, vault, title)
    assert written
    root = vault.resolve()
    for path in written:
        assert path.resolve().is_relative_to(root)
    # Each game gets exactly one folder directly under the vault.
    assert len(list(vault.iterdir())) == 1
    assert sorted(item.name for item in tmp_path.iterdir()) == ["vault"]


def test_safe_name_leaves_reserved_names_unusable_as_devices() -> None:
    for title in ["CON", "con.txt", "NUL", "COM1", "LPT9.md"]:
        assert safe_name(title).startswith("_")


def test_safe_name_keeps_ordinary_titles_unchanged() -> None:
    assert safe_name("Terraria") == "Terraria"
    assert safe_name("Hollow Knight 2") == "Hollow Knight 2"


def test_titles_that_clean_to_the_same_name_get_separate_folders() -> None:
    assert safe_name("A/B") != safe_name("A B")
    assert safe_name("A/B") != safe_name("A:B")


def test_rerun_writes_nothing_new(conn: sqlite3.Connection, tmp_path: Path) -> None:
    session = add_session(conn)
    add_note(conn, session, "recap", "the recap")
    assert export_vault(conn, tmp_path, "Game")
    before = {path: path.stat().st_mtime_ns for path in tmp_path.rglob("*.md")}
    assert export_vault(conn, tmp_path, "Game") == []
    assert {path: path.stat().st_mtime_ns for path in tmp_path.rglob("*.md")} == before


def test_only_changed_files_are_rewritten(conn: sqlite3.Connection, tmp_path: Path) -> None:
    add_session(conn)
    export_vault(conn, tmp_path, "Game")
    add_fact(conn, "Base", "location", "east")
    assert [path.name for path in export_vault(conn, tmp_path, "Game")] == ["Facts.md"]


def test_leaves_no_temporary_files(conn: sqlite3.Connection, tmp_path: Path) -> None:
    add_session(conn)
    export_vault(conn, tmp_path, "Game")
    assert not list(tmp_path.rglob("*.tmp"))


def test_never_deletes_files_it_did_not_write(conn: sqlite3.Connection, tmp_path: Path) -> None:
    mine = tmp_path / "Game" / "My own note.md"
    mine.parent.mkdir()
    mine.write_text("keep me", encoding="utf-8")
    add_session(conn)
    export_vault(conn, tmp_path, "Game")
    assert mine.read_text(encoding="utf-8") == "keep me"


def test_live_export_rebuilds_only_the_live_page(conn: sqlite3.Connection, tmp_path: Path) -> None:
    past, live = add_session(conn), add_session(conn)
    export_vault(conn, tmp_path, "Game")
    add_note(conn, past, "rolling", "added to the past")
    add_note(conn, live, "rolling", "added to the live one")
    written = export_vault(conn, tmp_path, "Game", live_session=live)
    assert [path.name for path in written] == [f"{session_file(live)}.md"]
    past_page = tmp_path / "Game" / "Sessions" / f"{session_file(past)}.md"
    assert "added to the past" not in past_page.read_text(encoding="utf-8")


def test_live_export_writes_missing_past_pages(conn: sqlite3.Connection, tmp_path: Path) -> None:
    past, live = add_session(conn), add_session(conn)
    sessions = tmp_path / "Game" / "Sessions"
    export_vault(conn, tmp_path, "Game", live_session=live)
    assert {path.name for path in sessions.iterdir()} == {
        f"{session_file(past)}.md",
        f"{session_file(live)}.md",
    }
    page = sessions / f"{session_file(past)}.md"
    page.unlink()
    assert export_vault(conn, tmp_path, "Game", live_session=live) == [page]
