"""The apps with a window open, so the player can say which one is the game.

Listing happens only in the terminal, locally. Nothing here captures pixels.
"""

from collections.abc import Iterable
from dataclasses import dataclass

# The overlay's own window, which is never the game.
_NEVER_THE_GAME = frozenset({"electron"})

# Apps the player passes through on the way to the game: where they started the brain, the
# desktop, launchers and the usual tools. Spotting the game skips them when they come to the
# front. Lowercase, matched against AppWindow.process.
NOT_A_GAME = _NEVER_THE_GAME | {
    # Terminals and editors
    "terminal", "iterm2", "warp", "ghostty", "alacritty", "kitty", "wezterm-gui",
    "windowsterminal", "cmd", "powershell", "pwsh", "conhost", "openconsole",
    "code", "code - insiders", "cursor", "zed", "pycharm", "pycharm64", "idea64", "sublime_text",
    # Desktops and system UI
    "finder", "dock", "system settings", "systemsettings", "explorer", "searchhost",
    "startmenuexperiencehost", "shellexperiencehost", "textinputhost", "lockapp",
    "applicationframehost", "taskmgr", "activity monitor",
    # Browsers, chat, recording and launchers
    "chrome", "google chrome", "msedge", "microsoft edge", "firefox", "safari", "arc", "brave",
    "discord", "slack", "obs", "obs64", "obs studio",
    "steam", "steam helper", "steamwebhelper", "epicgameslauncher", "battle.net", "galaxyclient",
    "claude", "github desktop",
}  # fmt: skip


def is_not_a_game(app: "AppWindow") -> bool:
    return app.process.strip().lower() in NOT_A_GAME


def title_names_game(wanted: str, app: "AppWindow") -> bool:
    """True when the window's title starts with `wanted` as a whole word.

    Players type the game's name where the exe's stem belongs, and some games share a generic
    exe: Minecraft Java runs as javaw, titled "Minecraft 1.12.2". Apps from NOT_A_GAME never
    count, because a browser tab or an editor file about the game isn't the game.
    """
    wanted, title = wanted.strip().lower(), app.title.strip().lower()
    if not wanted or is_not_a_game(app) or not title.startswith(wanted):
        return False
    rest = title[len(wanted) :]
    return not rest or not rest[0].isalnum()


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
