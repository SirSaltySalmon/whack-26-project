"""The apps with a window open, so the player can say which one is the game.

Listing happens only in the terminal, locally. Nothing here captures pixels.
"""

from collections.abc import Iterable
from dataclasses import dataclass

# The overlay's own window, which is never the game.
_NEVER_THE_GAME = frozenset({"electron"})


@dataclass(frozen=True)
class AppWindow:
    process: str  # What GameWindow matches: the exe's stem on Windows, the app's name on macOS
    name: str  # The app's name, as the player knows it
    title: str  # The window's title. Can be empty, and is data from another app

    @property
    def label(self) -> str:
        return f"{self.name}: {self.title}" if self.title and self.title != self.name else self.name

    @property
    def hint(self) -> str:
        """What identifies the game to a model: the app's name, plus the title if it has one."""
        return f'app "{self.name}", window "{self.title}"' if self.title else f'app "{self.name}"'


def unique_apps(windows: Iterable[AppWindow]) -> list[AppWindow]:
    """One entry per app, in a stable order, since the window list changes order as focus moves."""
    seen: dict[str, AppWindow] = {}
    for window in windows:
        process = window.process.strip().lower()
        if not process or process in _NEVER_THE_GAME or process in seen:
            continue
        seen[process] = AppWindow(process, window.name.strip() or process, window.title.strip())
    return sorted(seen.values(), key=lambda app: app.name.casefold())
