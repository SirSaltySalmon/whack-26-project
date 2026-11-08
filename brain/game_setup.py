"""Works out which game is being played, so nothing in the brain has to assume one.

GAME_PROCESS and GAME_TITLE still win when set. Without GAME_PROCESS, the game's window is found
before anything starts (brain/game_detect.py): a game played here before if it's open, otherwise
the window the player switches to. Without
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
from brain.capture.window import window_lister
from brain.config import Settings
from brain.game_detect import DetectTiming, detect_game
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


def pick_game(
    settings: Settings,
    list_apps: Callable[[], list[AppWindow]] | None = None,
    front_app: Callable[[], AppWindow | None] | None = None,
    write: Callable[[str], object] = sys.stdout.write,
    interactive: bool | None = None,
    timing: DetectTiming | None = None,
) -> tuple[Settings, str]:
    """Settings with game_process set, and a hint that names the game to a model.

    Blocking, so call it before the event loop starts. In a terminal it waits for the player to
    switch to the game. Without one, as when the Control Center starts the brain, it waits a
    limited time and then falls back to the last pick, so the brain still comes up.
    """
    if settings.game_process:
        return settings, f'app "{settings.game_process}"'
    if list_apps is None or front_app is None:
        lister = window_lister()
        list_apps, front_app = list_apps or lister.app_windows, front_app or lister.front_app
    known = load_known(settings.games_path)
    remembered = list(dict.fromkeys([*([known.last] if known.last else []), *known.titles]))
    in_terminal = sys.stdin.isatty() if interactive is None else interactive
    if timing is None:
        timing = DetectTiming(timeout_s=None if in_terminal else settings.game_detect_timeout_s)
    app = detect_game(list_apps, front_app, remembered, write, timing)
    if app is None:
        if not in_terminal and known.last:
            log.info("Watching %s, the game picked last time", known.last)
            return settings.model_copy(update={"game_process": known.last}), f'app "{known.last}"'
        log.warning("No game found, so not capturing: set the game process, or switch to the game")
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
