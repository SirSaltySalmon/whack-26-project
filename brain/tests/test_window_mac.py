"""MacGameWindow with fake pyobjc modules, so these run on any platform."""

from types import SimpleNamespace
from typing import Any

from brain.capture.window_mac import MacGameWindow
from brain.perception.coords import CropRegion

OVERLAY = 1000  # Electron's "screen-saver" level sits far above normal windows.


def window(
    owner: str,
    pid: int,
    x: int = 0,
    y: int = 0,
    w: int = 800,
    h: int = 600,
    layer: int = 0,
    alpha: float = 1.0,
) -> dict[str, Any]:
    return {
        "kCGWindowOwnerName": owner,
        "kCGWindowOwnerPID": pid,
        "kCGWindowLayer": layer,
        "kCGWindowAlpha": alpha,
        "kCGWindowBounds": {"X": x, "Y": y, "Width": w, "Height": h},
    }


class FakeQuartz:
    kCGWindowListOptionOnScreenOnly = 1
    kCGWindowListExcludeDesktopElements = 16
    kCGNullWindowID = 0

    def __init__(self) -> None:
        self.windows: list[dict[str, Any]] = []

    def CGPreflightScreenCaptureAccess(self) -> bool:  # noqa: N802 - Quartz's name.
        return True

    def CGWindowListCopyWindowInfo(self, _options: int, _relative: int) -> list[Any]:  # noqa: N802
        return self.windows


def fake_appkit(executables: dict[int, str]) -> Any:
    def lookup(pid: int) -> Any:
        path = executables.get(pid)
        if path is None:
            return None
        url = SimpleNamespace(path=lambda: path)
        return SimpleNamespace(executableURL=lambda: url)

    return SimpleNamespace(
        NSRunningApplication=SimpleNamespace(runningApplicationWithProcessIdentifier_=lookup)
    )


def make(process: str = "Terraria", executables: dict[int, str] | None = None):
    quartz = FakeQuartz()
    return MacGameWindow(process, quartz, fake_appkit(executables or {})), quartz


def test_game_in_front_gives_its_bounds() -> None:
    game, quartz = make()
    quartz.windows = [
        window("Electron", 9, w=1440, h=900, layer=OVERLAY),
        window("Terraria", 5, x=10, y=40, w=1280, h=720),
        window("Finder", 6),
    ]
    assert game.visible_region() == CropRegion(10, 40, 1280, 720)


def test_another_app_in_front_stops_capture() -> None:
    game, quartz = make()
    quartz.windows = [window("Terminal", 6), window("Terraria", 5)]
    assert game.visible_region() is None


def test_tiny_and_invisible_helper_windows_do_not_count_as_in_front() -> None:
    game, quartz = make()
    quartz.windows = [
        window("Helper", 7, w=20, h=20),
        window("Ghost", 8, alpha=0.0),
        window("Terraria", 5),
    ]
    assert game.visible_region() == CropRegion(0, 0, 800, 600)


def test_game_not_on_screen_gives_none() -> None:
    game, quartz = make()
    quartz.windows = [window("Finder", 6)]
    assert game.visible_region() is None


def test_matches_by_executable_name_too() -> None:
    game, quartz = make(executables={5: "/Games/Terraria.app/Contents/MacOS/Terraria.bin.osx"})
    quartz.windows = [window("Some Launcher Name", 5)]
    assert game.visible_region() == CropRegion(0, 0, 800, 600)


def test_unset_process_never_captures() -> None:
    game, quartz = make(process="")
    quartz.windows = [window("", 5)]
    assert game.visible_region() is None
