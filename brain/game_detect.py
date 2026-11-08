"""Spots the game's window without the player typing anything.

Two ways, in order. A game picked on an earlier launch is taken straight away if it has a window
open. Otherwise the brain waits for the player to bring an app to the front, and takes the first
one that isn't where they started the brain or a known non-game (terminals, browsers, launchers).
It never guesses from window titles or sends them anywhere: frames of whatever it picks go on to
cloud models, so the pick has to be the player's own action.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from brain.capture.apps import AppWindow, is_not_a_game

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DetectTiming:
    poll_s: float = 0.5
    # The app must stay in front this long, so passing through it while alt-tabbing doesn't count.
    settle_s: float = 1.0
    # None waits until the player switches or presses Ctrl+C.
    timeout_s: float | None = None


_DEFAULT_TIMING = DetectTiming()


def remembered_running(apps: list[AppWindow], remembered: list[str]) -> AppWindow | None:
    """The first remembered game, in the order given, that has a window open now."""
    by_process = {app.process: app for app in apps}
    return next((by_process[p] for p in remembered if p in by_process), None)


def wait_for_front(
    front_app: Callable[[], AppWindow | None],
    timing: DetectTiming = _DEFAULT_TIMING,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> AppWindow | None:
    """The first app the player brings to the front and keeps there, or None on timeout."""
    start = front_app()
    started_in = start.process if start else None
    began = clock()
    candidate: AppWindow | None = None
    since = 0.0
    while timing.timeout_s is None or clock() - began < timing.timeout_s:
        front = front_app()
        if front is None or front.process == started_in or is_not_a_game(front):
            candidate = None
        elif candidate is None or front.process != candidate.process:
            candidate, since = front, clock()
        elif clock() - since >= timing.settle_s:
            return candidate
        sleep(timing.poll_s)
    return None


def detect_game(
    list_apps: Callable[[], list[AppWindow]],
    front_app: Callable[[], AppWindow | None],
    remembered: list[str],
    write: Callable[[str], object],
    timing: DetectTiming = _DEFAULT_TIMING,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> AppWindow | None:
    """The game's window, or None if the player never switched to one in time."""
    try:
        known = remembered_running(list_apps(), remembered)
    except Exception:
        log.exception("Couldn't list app windows; waiting for the game to come to the front")
        known = None
    if known is not None:
        log.info("Found %s, played here before", known.label)
        return known
    write("\nSwitch to your game now. I'll pick whichever window you bring to the front.\n")
    if timing.timeout_s is None:
        write("(Ctrl+C to stop.)\n")
    try:
        app = wait_for_front(front_app, timing, sleep, clock)
    except Exception:
        log.exception("Couldn't read the front window, so no game was found")
        return None
    if app is not None:
        write(f"Got it: {app.label}\n")
    return app
