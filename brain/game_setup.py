"""Works out which game is being played, so nothing in the brain has to assume one.

GAME_PROCESS and GAME_TITLE still win when set. Without GAME_PROCESS, the player picks the game's
window in the terminal before anything starts, since its frames go on to cloud models. Without
GAME_TITLE, the deep model names the game once per app, and the name is kept in `games_path` so
memory stays filed under one title even when the window title changes each launch.
"""

import json
import logging
import sys
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from brain.capture.apps import AppWindow
from brain.capture.window import list_app_windows
from brain.config import Settings
from brain.learner.brief import GameBrief, ask_brief
from brain.llm.base import TextLLM
from brain.memory.db import Database
from brain.memory.profile import ProfileStore

log = logging.getLogger(__name__)


class KnownGames(BaseModel):
    last: str | None = None  # The process picked last time, offered as the default
    titles: dict[str, str] = Field(default_factory=dict)  # Process name to game title


def load_known(path: Path) -> KnownGames:
    try:
        return KnownGames.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return KnownGames()
    except (OSError, ValidationError, ValueError):
        log.warning("Ignoring unreadable %s; games will be picked and named again", path)
        return KnownGames()


def save_known(path: Path, known: KnownGames) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(known.model_dump(), indent=2), encoding="utf-8")
    except OSError:
        log.exception("Couldn't save %s; the game will be picked or named again", path)


def choose(
    list_apps: Callable[[], list[AppWindow]],
    last: str | None,
    read_line: Callable[[], str],
    write: Callable[[str], object],
) -> AppWindow | None:
    """Asks in the terminal until the player picks an app or skips. None means don't capture."""
    while True:
        apps = list_apps()
        default = next((app for app in apps if app.process == last), None)
        if apps:
            write("\nWhich window is your game?\n")
            for number, app in enumerate(apps, 1):
                write(f"  {number}. {app.label}{'  (last time)' if app is default else ''}\n")
            enter = f"Enter for {default.name}, " if default else "Enter to refresh, "
            write(f"Type its number ({enter}r to refresh, q to skip capture): ")
        else:
            write("\nNo app windows found. Start the game, then press Enter (q to skip): ")
        try:
            answer = read_line().strip().lower()
        except EOFError:
            return None
        if answer == "q":
            return None
        if answer == "" and default is not None:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(apps):
            return apps[int(answer) - 1]
        if answer not in ("", "r"):
            write("That isn't one of the numbers.\n")


def pick_game(
    settings: Settings,
    list_apps: Callable[[], list[AppWindow]] = list_app_windows,
    read_line: Callable[[], str] = input,
    write: Callable[[str], object] = sys.stdout.write,
    interactive: bool | None = None,
) -> tuple[Settings, str]:
    """Settings with game_process set, and a hint that names the game to a model.

    Blocking, so call it before the event loop starts: Ctrl+C can't interrupt input() on a thread.
    """
    if settings.game_process:
        return settings, f'app "{settings.game_process}"'
    known = load_known(settings.games_path)
    if not (sys.stdin.isatty() if interactive is None else interactive):
        # The Control Center starts the brain with stdin as a pipe, so nobody could answer.
        if known.last:
            log.info("Watching %s, the game picked last time", known.last)
            return settings.model_copy(update={"game_process": known.last}), f'app "{known.last}"'
        log.warning("No game to watch: set the game process, or start the brain in a terminal")
        return settings, ""
    app = choose(list_apps, known.last, read_line, write)
    if app is None:
        log.warning("No game picked, so not capturing")
        return settings, ""
    known.last = app.process
    save_known(settings.games_path, known)
    log.info("Watching %s", app.label)
    return settings.model_copy(update={"game_process": app.process}), app.hint


async def name_game(
    settings: Settings, llm: Callable[[], TextLLM], hint: str
) -> tuple[Settings, GameBrief | None]:
    """Settings with game_title set, and the brief if one was written while naming the game."""
    process = settings.game_process
    if "game_title" in settings.model_fields_set or not process:
        return settings, None
    known = load_known(settings.games_path)
    if process in known.titles:
        return settings.model_copy(update={"game_title": known.titles[process]}), None
    brief = await ask_brief(llm, hint, None, settings.brief_timeout_s)
    if brief is None:
        # Not saved, so the next launch asks again. Memory is filed under the app for now.
        return settings.model_copy(update={"game_title": process}), None
    # An unknown game keeps the app's name for good: asking again would get the same answer.
    title = brief.title or process
    known.titles[process] = title
    save_known(settings.games_path, known)
    log.info("Playing %s", title)
    return settings.model_copy(update={"game_title": title}), brief


async def ensure_brief(
    database: Database,
    title: str,
    llm: Callable[[], TextLLM],
    hint: str,
    written: GameBrief | None,
    timeout_s: float,
) -> None:
    """Fills in the profile's brief if it has none. Run in the background: the talker reads the
    profile on every turn, so the brief is used as soon as it lands."""
    current = await database.run(lambda conn: ProfileStore(conn).get(title).brief)
    if current.strip():
        return
    # A naming call this launch already said what it knows, even if that was nothing.
    brief = written if written is not None else await ask_brief(llm, hint, title, timeout_s)
    if brief is None or not brief.summary:
        return
    summary = brief.summary
    await database.run(lambda conn: ProfileStore(conn).set_brief(title, summary))
    log.info("Learned a brief on %s", title)
