from pathlib import Path

from pydantic import SecretStr

from brain.capture.apps import AppWindow, title_names_game, unique_apps
from brain.config import Settings
from brain.game_detect import DetectTiming, wait_for_front
from brain.game_setup import (
    KnownGames,
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


TERMINAL = AppWindow("terminal", "Terminal", "zsh")
NOW = DetectTiming(poll_s=0, settle_s=0, timeout_s=None)


def fronts(*apps: AppWindow | None):  # type: ignore[no-untyped-def]
    """The front app on each poll, ending on the last one for good."""
    remaining = list(apps)
    return lambda: remaining.pop(0) if len(remaining) > 1 else remaining[0]


def detect(tmp_path: Path, running: list[AppWindow], front, **kwargs: object):  # type: ignore[no-untyped-def]
    return pick_game(settings(tmp_path), lambda: running, front, lambda _: None, **kwargs)  # type: ignore[arg-type]


def test_unique_apps_keeps_one_per_app_and_never_offers_the_overlay() -> None:
    windows = [CHROME, AppWindow("Chrome", "chrome", "Other tab"), AppWindow("electron", "x", "y")]
    assert unique_apps(windows) == [CHROME]


def test_a_game_name_finds_its_window_by_title_when_the_exe_is_generic() -> None:
    minecraft = AppWindow("javaw", "javaw", "Minecraft 1.12.2")
    assert title_names_game("Minecraft", minecraft)
    assert title_names_game(" minecraft 1.12.2 ", minecraft)
    # Only a whole word counts, and the name must start the title.
    assert not title_names_game("Mine", minecraft)
    assert not title_names_game("1.12.2", minecraft)
    assert not title_names_game("", minecraft)


def test_a_page_about_the_game_is_never_the_game() -> None:
    for process in ("msedge", "discord", "code", "explorer"):
        assert not title_names_game("Minecraft", AppWindow(process, process, "Minecraft Wiki"))


def test_pick_game_uses_game_process_without_asking(tmp_path: Path) -> None:
    picked, hint = pick_game(settings(tmp_path, game_process="hades"), lambda: [], lambda: None)
    assert picked.game_process == "hades" and "hades" in hint


def test_it_takes_the_window_the_player_switches_to_and_remembers_it(tmp_path: Path) -> None:
    picked, hint = detect(
        tmp_path, [CHROME, HADES], fronts(TERMINAL, TERMINAL, HADES), interactive=True, timing=NOW
    )
    assert picked.game_process == "hades" and "Hades" in hint
    assert load_known(tmp_path / "games.json").last == "hades"


def test_it_skips_where_the_brain_started_and_known_non_games(tmp_path: Path) -> None:
    other = AppWindow("notes", "Notes", "")
    front = fronts(other, other, CHROME, AppWindow("Steam", "Steam", ""), HADES)
    # Notes was in front at the start, so it's where the player launched the brain.
    assert detect(tmp_path, [], front, interactive=True, timing=NOW)[0].game_process == "hades"


def test_an_app_passed_while_alt_tabbing_doesnt_count(tmp_path: Path) -> None:
    clock = iter(range(100))
    passing = AppWindow("mail", "Mail", "")
    picked = wait_for_front(
        fronts(TERMINAL, passing, TERMINAL, HADES, HADES, HADES),
        DetectTiming(poll_s=0, settle_s=2),
        sleep=lambda _: None,
        clock=lambda: float(next(clock)),
    )
    assert picked == HADES


def test_a_game_played_before_is_taken_at_once_if_open(tmp_path: Path) -> None:
    save_known(tmp_path / "games.json", KnownGames(last="chrome", titles={"hades": "Hades"}))
    never = fronts(None)
    assert detect(tmp_path, [HADES], never, interactive=True)[0].game_process == "hades"


def test_without_a_terminal_it_times_out_to_the_last_pick_or_nothing(tmp_path: Path) -> None:
    quick = DetectTiming(poll_s=0, settle_s=0, timeout_s=0)

    def found() -> str:
        picked, _ = detect(tmp_path, [], fronts(TERMINAL), interactive=False, timing=quick)
        return picked.game_process

    assert found() == ""
    save_known(tmp_path / "games.json", KnownGames(last="hades"))
    assert found() == "hades"


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
