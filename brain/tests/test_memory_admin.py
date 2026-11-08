import io
import socket
import sqlite3
from pathlib import Path

import pytest

from brain.director.director import Director
from brain.events import EventBus
from brain.memory.admin import administer
from brain.memory.db import connect
from brain.memory.facts import FactStore
from brain.memory.profile import PlayerStore, ProfileStore
from brain.tests.fakes import FakeVoice
from shared.protocol.admin import MemoryAdminRequest
from shared.protocol.messages import Settings


def test_correction_preserves_history_and_forget_rejects_old_guess(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    conn = connect(path)
    try:
        first = administer(
            conn,
            path,
            MemoryAdminRequest(
                operation="remember",
                game="Game",
                subject="player",
                attribute="goal",
                value="explore",
            ),
        ).facts[0]
        corrected = administer(
            conn, path, MemoryAdminRequest(operation="remember", fact_id=first.id, value="build")
        ).facts[0]
        assert corrected.value == "build" and corrected.source == "player"
        assert corrected.confidence == 1 and corrected.game == "Game"
        assert conn.execute("SELECT valid_to FROM facts WHERE id = ?", (first.id,)).fetchone()[0]
        with pytest.raises(ValueError, match="no longer current"):
            administer(conn, path, MemoryAdminRequest(operation="forget", fact_id=first.id))
        result = administer(
            conn, path, MemoryAdminRequest(operation="forget", fact_id=corrected.id)
        )
        assert result.total_facts == 0
        FactStore(conn).remember("Game", "player", "goal", "build", "observed", 0.9)
        assert not FactStore(conn).current("Game")
    finally:
        conn.close()


def test_clear_removes_personal_data_and_vectors_but_preserves_settings_and_profile(
    tmp_path: Path,
) -> None:
    from brain.memory.vectors import prepare

    path = tmp_path / "memory.db"
    conn = connect(path)
    try:
        FactStore(conn).remember(None, "player", "name", "Sam", "player", 1)
        PlayerStore(conn).save_settings(Settings(custom_instructions="Avoid spoilers"))
        PlayerStore(conn).set("nickname", "Sam")
        ProfileStore(conn).set_brief("Game", "A learned game")
        with conn:
            conn.execute("INSERT INTO sessions (game, started_at) VALUES ('Game', 1)")
            conn.execute("INSERT INTO events (session_id, ts, name) VALUES (1, 1, 'turn.player')")
            conn.execute(
                "INSERT INTO session_notes (session_id, kind, body, from_ts, to_ts, created_at) "
                "VALUES (1, 'rolling', 'Sam was here', 1, 2, 2)"
            )
            conn.execute(
                "INSERT INTO questions (game, text, created_at) VALUES ('Game', 'Who?', 1)"
            )
        prepare(conn, "test", 3)
        with pytest.raises(ValueError, match="Type CLEAR"):
            administer(conn, path, MemoryAdminRequest(operation="clear"))
        assert FactStore(conn).current(None)
        result = administer(conn, path, MemoryAdminRequest(operation="clear", confirmation="CLEAR"))
        assert (result.total_facts, result.notes, result.events, result.questions) == (0, 0, 0, 0)
        assert not conn.execute("SELECT 1 FROM sessions").fetchall()
        assert not conn.execute("SELECT 1 FROM facts_fts WHERE facts_fts MATCH 'Sam'").fetchall()
        assert not conn.execute(
            "SELECT 1 FROM session_notes_fts WHERE session_notes_fts MATCH 'Sam'"
        ).fetchall()
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'fact_vectors'"
        ).fetchall()
        assert PlayerStore(conn).get("nickname") is None
        assert PlayerStore(conn).load_settings(Settings).custom_instructions == "Avoid spoilers"
        assert ProfileStore(conn).get("Game").brief == "A learned game"
        assert result.backup
        with sqlite3.connect(result.backup) as backup:
            assert backup.execute("SELECT count(*) FROM facts").fetchone()[0] == 1
    finally:
        conn.close()


def test_custom_instructions_are_read_fresh_for_each_turn() -> None:
    instructions = "Avoid spoilers"
    director = Director(
        EventBus(), FakeVoice(), proactive=lambda: True, custom_instructions=lambda: instructions
    )
    assert instructions in director._persona().tone
    instructions = "Focus on building"
    assert instructions in director._persona().tone
    assert "Avoid spoilers" not in director._persona().tone


def test_offline_helper_refuses_a_running_brain_before_opening_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from brain.memory.admin import main

    with socket.socket() as running:
        running.bind(("127.0.0.1", 0))
        running.listen(1)
        path = tmp_path / "must-not-exist.db"
        monkeypatch.setenv("BRAIN_PORT", str(running.getsockname()[1]))
        monkeypatch.setenv("DB_PATH", str(path))
        monkeypatch.setattr("sys.stdin", io.StringIO('{"operation":"list"}'))
        with pytest.raises(RuntimeError, match="Stop the running brain"):
            main()
        assert not path.exists()


async def test_instructions_reach_both_plain_and_tool_model_prompts() -> None:
    from brain.agent.tools import ToolRegistry, TurnContext
    from brain.agent.turn import run_turn
    from brain.director.turns import talker_reply
    from brain.llm.base import ToolStep
    from brain.tests.fakes import FakeTextLLM, ScriptedToolLLM

    director = Director(
        EventBus(),
        FakeVoice(),
        proactive=lambda: True,
        custom_instructions=lambda: "Focus on building",
    )
    persona = director._persona()
    plain = FakeTextLLM(["Let's build."])
    await talker_reply(plain, "hello", persona, "Untrusted memory")
    assert "Focus on building" in plain.system
    assert "Focus on building" in plain.system.split("reference data")[0]

    async def no_filler() -> None:
        pass

    agent = ScriptedToolLLM([ToolStep("Let's build.")])
    await run_turn(
        agent,
        ToolRegistry([]),
        "hello",
        persona.name,
        persona.tone,
        persona.max_words,
        "",
        TurnContext(),
        no_filler,
        "Done.",
    )
    assert "Focus on building" in agent.system
