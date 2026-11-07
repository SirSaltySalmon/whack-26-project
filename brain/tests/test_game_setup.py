from pathlib import Path

from pydantic import SecretStr

from brain.capture.apps import AppWindow, unique_apps
from brain.config import Settings
from brain.game_setup import (
    KnownGames,
    choose,
    ensure_brief,
    load_known,
    name_game,
    pick_game,
    save_known,
)
from brain.learner.brief import MAX_BRIEF_WORDS, GameBrief, ask_brief, parse_brief
from brain.llm.base import LLMUnavailableError
from brain.memory.db import Database, connect
from brain.memory.profile import ProfileStore
from brain.tests.fakes import FakeTextLLM

HADES = AppWindow("hades", "Hades", "Hades")
CHROME = AppWindow("chrome", "chrome", "Inbox - Mail")
REPLY = "TITLE: Hades\nBRIEF: A roguelike dungeon crawler.\nEscape the underworld."


def settings(tmp_path: Path, **values: object) -> Settings:
    return Settings(_env_file=None, games_path=tmp_path / "games.json", **values)  # type: ignore[call-arg]


def answers(*lines: str):  # type: ignore[no-untyped-def]
    remaining = list(lines)

    def read() -> str:
        if not remaining:
            raise EOFError
        return remaining.pop(0)

    return read


def pick(apps: list[AppWindow], last: str | None, *lines: str) -> AppWindow | None:
    return choose(lambda: apps, last, answers(*lines), lambda _: None)


def test_unique_apps_keeps_one_per_app_and_never_offers_the_overlay() -> None:
    windows = [CHROME, AppWindow("Chrome", "chrome", "Other tab"), AppWindow("electron", "x", "y")]
    assert unique_apps(windows) == [CHROME]


def test_choose_takes_a_number() -> None:
    assert pick([CHROME, HADES], None, "2") == HADES


def test_choose_offers_last_time_on_enter() -> None:
    assert pick([CHROME, HADES], "hades", "") == HADES


def test_choose_asks_again_after_a_bad_answer_or_a_refresh() -> None:
    assert pick([CHROME, HADES], None, "9", "r", "", "1") == CHROME


def test_choose_skips_on_q_or_end_of_input() -> None:
    assert pick([HADES], None, "q") is None
    assert pick([HADES], None) is None


def test_pick_game_uses_game_process_without_asking(tmp_path: Path) -> None:
    picked, hint = pick_game(settings(tmp_path, game_process="hades"), read_line=answers())
    assert picked.game_process == "hades" and "hades" in hint


def test_pick_game_remembers_the_pick(tmp_path: Path) -> None:
    base = settings(tmp_path)
    picked, hint = pick_game(base, lambda: [HADES], answers("1"), lambda _: None, interactive=True)
    assert picked.game_process == "hades" and "Hades" in hint
    assert load_known(base.games_path).last == "hades"


def test_without_a_terminal_it_reuses_the_last_pick_or_captures_nothing(tmp_path: Path) -> None:
    base = settings(tmp_path)
    assert pick_game(base, interactive=False)[0].game_process == ""
    save_known(base.games_path, KnownGames(last="hades"))
    assert pick_game(base, interactive=False)[0].game_process == "hades"


def test_an_unreadable_games_file_starts_fresh(tmp_path: Path) -> None:
    path = tmp_path / "games.json"
    path.write_text("not json")
    assert load_known(path) == KnownGames()


def test_parse_brief_reads_both_fields_across_lines() -> None:
    assert parse_brief(REPLY) == GameBrief(
        "Hades", "A roguelike dungeon crawler. Escape the underworld."
    )


def test_parse_brief_treats_unknown_as_no_game_and_caps_the_length() -> None:
    assert parse_brief("TITLE: UNKNOWN\nBRIEF:") == GameBrief(None, "")
    long = parse_brief("TITLE: X\nBRIEF: " + "word " * 200)
    assert len(long.summary.split()) == MAX_BRIEF_WORDS


async def test_ask_brief_returns_none_when_the_model_fails() -> None:
    llm = FakeTextLLM(error=LLMUnavailableError("no key"))
    assert await ask_brief(lambda: llm, 'app "hades"', None, 5) is None


async def test_name_game_asks_once_then_remembers_the_title(tmp_path: Path) -> None:
    llm = FakeTextLLM([REPLY])
    base = settings(tmp_path, game_process="hades")
    named, brief = await name_game(base, lambda: llm, 'app "Hades"')
    assert named.game_title == "Hades" and brief is not None
    again, second = await name_game(base, lambda: llm, 'app "Hades"')
    assert again.game_title == "Hades" and second is None
    assert len(llm.prompts) == 1


async def test_name_game_keeps_a_title_the_player_set(tmp_path: Path) -> None:
    llm = FakeTextLLM([REPLY])
    named, _ = await name_game(
        settings(tmp_path, game_process="hades", game_title="Mine"), lambda: llm, "x"
    )
    assert named.game_title == "Mine" and llm.prompts == []


async def test_name_game_falls_back_to_the_app_and_retries_next_launch(tmp_path: Path) -> None:
    llm = FakeTextLLM(error=LLMUnavailableError("over quota"))
    base = settings(tmp_path, game_process="hades")
    named, _ = await name_game(base, lambda: llm, "x")
    assert named.game_title == "hades"
    assert load_known(base.games_path).titles == {}


async def test_ensure_brief_stores_the_brief_once() -> None:
    database = Database(connect(":memory:"))
    llm = FakeTextLLM([REPLY])
    await ensure_brief(database, "Hades", lambda: llm, "x", None, 5)
    await ensure_brief(database, "Hades", lambda: llm, "x", None, 5)
    stored = await database.run(lambda conn: ProfileStore(conn).get("Hades").brief)
    assert stored.startswith("A roguelike") and len(llm.prompts) == 1
    database.close()


async def test_ensure_brief_reuses_the_one_written_while_naming() -> None:
    database = Database(connect(":memory:"))
    llm = FakeTextLLM([REPLY])
    await ensure_brief(database, "Hades", lambda: llm, "x", GameBrief("Hades", "Escape."), 5)
    assert await database.run(lambda conn: ProfileStore(conn).get("Hades").brief) == "Escape."
    assert llm.prompts == []
    database.close()


def test_secret_import_kept() -> None:
    # Settings validation accepts keys alongside the games path.
    assert settings(Path("."), anthropic_api_key=SecretStr("k")).anthropic_api_key is not None
