"""The macOS version of GameWindow: where the game is on screen, only while it's in front.

Coordinates are in points, the same units as mss frames on macOS and the overlay's DIPs.

The frontmost app is read from the window list rather than NSWorkspace, because NSWorkspace only
updates from a main-thread run loop, and this runs on the capture thread. The window list is
ordered front to back, so the first normal window (layer 0) belongs to the app in front. The
overlay draws far above layer 0, so it never counts.
"""

import logging
import os
from typing import Any

from brain.capture.apps import AppWindow, unique_apps
from brain.perception.coords import CropRegion

log = logging.getLogger(__name__)

# Some apps keep invisible or tiny helper windows at layer 0; those aren't the front window.
_MIN_WINDOW_SIDE_PT = 100


class MacGameWindow:
    def __init__(self, process_name: str, quartz: Any = None, appkit: Any = None) -> None:
        """Tests pass fakes for the two pyobjc modules, so they run on any platform."""
        if quartz is None or appkit is None:
            import AppKit  # pyobjc ships no type stubs, so these are typed Any.
            import Quartz

            quartz, appkit = Quartz, AppKit
        self._quartz: Any = quartz
        self._appkit: Any = appkit
        self._process_name = process_name.lower().removesuffix(".app")
        self._last_state: str | None = None
        self._names_by_pid: dict[int, set[str]] = {}
        if not quartz.CGPreflightScreenCaptureAccess():
            # Without it, mss returns only the wallpaper, so the AI would see an empty desktop.
            log.error(
                "Screen Recording permission is missing. Allow it for this terminal in System "
                "Settings > Privacy & Security > Screen Recording, then restart it."
            )

    def visible_region(self) -> CropRegion | None:
        state, region = self._check()
        if state != self._last_state:
            log.info("Game window '%s': %s", self._process_name, state)
            self._last_state = state
        return region

    def app_windows(self) -> list[AppWindow]:
        """Apps with a normal window on screen, for the player to pick the game from.

        The owner's name is what _names matches. Titles need Screen Recording permission, so
        they can be empty.
        """
        found: list[AppWindow] = []
        for window in self._on_screen_windows():
            if self._is_normal(window):
                owner = str(window.get("kCGWindowOwnerName") or "")
                found.append(AppWindow(owner, owner, str(window.get("kCGWindowName") or "")))
        return unique_apps(found)

    def front_app(self) -> AppWindow | None:
        """The app with the frontmost normal window, so the brain can spot the game as the player
        switches to it."""
        window = next((w for w in self._on_screen_windows() if self._is_normal(w)), None)
        if window is None:
            return None
        owner = str(window.get("kCGWindowOwnerName") or "")
        apps = unique_apps([AppWindow(owner, owner, str(window.get("kCGWindowName") or ""))])
        return apps[0] if apps else None

    def _check(self) -> tuple[str, CropRegion | None]:
        if not self._process_name:
            return "GAME_PROCESS isn't set, so not capturing", None
        windows = self._on_screen_windows()
        game = [w for w in windows if self._is_game(w)]
        if not game:
            # Minimized windows aren't on screen, so they land here too.
            return "not running or not visible, so not capturing", None
        front = next((w for w in windows if self._is_normal(w)), None)
        if front is None or front["kCGWindowOwnerPID"] != game[0]["kCGWindowOwnerPID"]:
            return "not in front, so not capturing", None
        region = _region(front)
        if region is None:
            return "has no visible area, so not capturing", None
        return f"capturing {region.width}x{region.height}", region

    def _on_screen_windows(self) -> list[Any]:
        q = self._quartz
        options = q.kCGWindowListOptionOnScreenOnly | q.kCGWindowListExcludeDesktopElements
        return list(q.CGWindowListCopyWindowInfo(options, q.kCGNullWindowID) or [])

    def _is_normal(self, window: Any) -> bool:
        bounds = window.get("kCGWindowBounds") or {}
        return (
            window.get("kCGWindowLayer") == 0
            and window.get("kCGWindowAlpha", 1.0) > 0
            and bounds.get("Width", 0) >= _MIN_WINDOW_SIDE_PT
            and bounds.get("Height", 0) >= _MIN_WINDOW_SIDE_PT
        )

    def _is_game(self, window: Any) -> bool:
        if not self._is_normal(window):
            return False
        return self._process_name in self._names(window)

    def _names(self, window: Any) -> set[str]:
        """The app's display name and its executable's name, since GAME_PROCESS may be either."""
        pid = int(window["kCGWindowOwnerPID"])
        if pid not in self._names_by_pid:
            names = {str(window.get("kCGWindowOwnerName", "")).lower()}
            app = self._appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
            url = app.executableURL() if app else None
            if url is not None:
                # Mono and FNA games such as Terraria can run as "Terraria.bin.osx".
                executable = os.path.basename(str(url.path())).lower()
                names |= {executable, executable.split(".")[0]}
            self._names_by_pid[pid] = names
        return self._names_by_pid[pid]


def _region(window: Any) -> CropRegion | None:
    """The whole window, title bar included: macOS doesn't expose a client area here."""
    bounds = window.get("kCGWindowBounds") or {}
    width, height = int(bounds.get("Width", 0)), int(bounds.get("Height", 0))
    if width <= 0 or height <= 0:
        return None
    return CropRegion(int(bounds.get("X", 0)), int(bounds.get("Y", 0)), width, height)
