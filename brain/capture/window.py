"""Finds the game's window, so frames only ever contain the game.

Frames can reach a cloud model, so anything uncertain counts as "don't capture". The window is
matched by process name because game titles can change: Terraria's differs per launch and locale.
"""

import ctypes
import logging
import os
import sys
from ctypes import wintypes
from typing import Any

import numpy as np

from brain.capture.window_mac import MacGameWindow
from brain.perception.coords import CropRegion

log = logging.getLogger(__name__)

_DPI_PER_MONITOR_AWARE_V2 = wintypes.HANDLE(-4)
_GW_OWNER = 4
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def crop_to_region(image: np.ndarray, region: CropRegion) -> tuple[np.ndarray, CropRegion] | None:
    """Clips to the image, returning the crop and the area it really covers, or None if off-screen.

    The crop is a view, not a copy: the ring buffer copies it on push.
    """
    height, width = image.shape[:2]
    left, top = max(0, region.x), max(0, region.y)
    right = min(width, region.x + region.width)
    bottom = min(height, region.y + region.height)
    if left >= right or top >= bottom:
        return None
    return image[top:bottom, left:right], CropRegion(left, top, right - left, bottom - top)


class GameWindow:
    """Reports where the game is on screen, but only while the player has it in front."""

    def __init__(self, process_name: str) -> None:
        self._process_name = process_name.lower().removesuffix(".exe")
        self._hwnd: int | None = None
        self._last_state: str | None = None
        self._user32: Any = ctypes.WinDLL("user32")
        self._kernel32: Any = ctypes.WinDLL("kernel32")
        self._declare_signatures()
        # Without this, Windows reports scaled coordinates that don't match dxcam's physical pixels.
        self._user32.SetProcessDpiAwarenessContext(_DPI_PER_MONITOR_AWARE_V2)

    def visible_region(self) -> CropRegion | None:
        state, region = self._check()
        if state != self._last_state:
            log.info("Game window '%s': %s", self._process_name, state)
            self._last_state = state
        return region

    def _check(self) -> tuple[str, CropRegion | None]:
        if not self._process_name:
            return "GAME_PROCESS isn't set, so not capturing", None
        if self._hwnd is None or not self._user32.IsWindow(self._hwnd):
            self._hwnd = self._find_window()
        if self._hwnd is None:
            return "not running, so not capturing", None
        if self._user32.GetForegroundWindow() != self._hwnd:
            return "not in front, so not capturing", None
        if self._user32.IsIconic(self._hwnd):
            return "minimized, so not capturing", None
        region = self._client_region(self._hwnd)
        if region is None:
            return "has no visible area, so not capturing", None
        return f"capturing {region.width}x{region.height}", region

    def _find_window(self) -> int | None:
        found: list[int] = []

        def check(hwnd: int, _: int) -> bool:
            if self._is_game_window(hwnd):
                found.append(hwnd)
                return False
            return True

        callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(check)
        self._user32.EnumWindows(callback, 0)
        return found[0] if found else None

    def _is_game_window(self, hwnd: int) -> bool:
        if not self._user32.IsWindowVisible(hwnd) or self._user32.GetWindow(hwnd, _GW_OWNER):
            return False
        process_id = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        return self._process_stem(process_id.value) == self._process_name

    def _process_stem(self, process_id: int) -> str | None:
        handle = self._kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
        if not handle:
            return None  # Protected system processes refuse this, and they aren't the game.
        try:
            path = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(path))
            if not self._kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                return None
            return os.path.splitext(os.path.basename(path.value))[0].lower()
        finally:
            self._kernel32.CloseHandle(handle)

    def _client_region(self, hwnd: int) -> CropRegion | None:
        """The window's contents, leaving out any title bar and borders."""
        rect = wintypes.RECT()
        origin = wintypes.POINT(0, 0)
        if not self._user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        if not self._user32.ClientToScreen(hwnd, ctypes.byref(origin)):
            return None
        if rect.right <= 0 or rect.bottom <= 0:
            return None
        return CropRegion(origin.x, origin.y, rect.right, rect.bottom)

    def _declare_signatures(self) -> None:
        # Handles are 64-bit here, and ctypes would otherwise truncate them to a C int.
        user32, kernel32 = self._user32, self._kernel32
        hwnd = wintypes.HWND
        user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
        user32.GetClientRect.argtypes = [hwnd, ctypes.POINTER(wintypes.RECT)]
        user32.ClientToScreen.argtypes = [hwnd, ctypes.POINTER(wintypes.POINT)]
        user32.GetForegroundWindow.restype = hwnd
        user32.GetWindow.argtypes = [hwnd, wintypes.UINT]
        user32.GetWindow.restype = hwnd
        user32.GetWindowThreadProcessId.argtypes = [hwnd, ctypes.POINTER(wintypes.DWORD)]
        user32.IsIconic.argtypes = [hwnd]
        user32.IsWindow.argtypes = [hwnd]
        user32.IsWindowVisible.argtypes = [hwnd]
        user32.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def create_game_window(process_name: str) -> "GameWindow | MacGameWindow":
    if sys.platform == "darwin":
        return MacGameWindow(process_name)
    return GameWindow(process_name)
