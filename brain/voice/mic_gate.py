"""When the mic is let through to speech recognition: push to talk, and the echo window.

Push to talk reads whether a key is held with Windows' GetAsyncKeyState, on each mic frame. That
works while the game has the keyboard, needs no hook or extra package, and sees the key being
let go, which Electron's global shortcuts can't. Elsewhere it isn't available: the mic stays muted
in push-to-talk mode and it says so once, rather than silently listening all the time.
"""

import ctypes
import logging
import sys
import time
from collections.abc import Callable

log = logging.getLogger(__name__)

# Windows virtual-key codes for the names PUSH_TO_TALK_KEY accepts. Letters and digits are their
# own codes. Backtick is the default: Terraria doesn't use it, and it's under the left hand.
_NAMED_KEYS = {
    "`": 0xC0,
    "backtick": 0xC0,
    "mouse4": 0x05,
    "mouse5": 0x06,
    "caps_lock": 0x14,
    "tab": 0x09,
    "alt": 0x12,
    "left_alt": 0xA4,
    "right_alt": 0xA5,
    "ctrl": 0x11,
    "left_ctrl": 0xA2,
    "right_ctrl": 0xA3,
    "shift": 0x10,
    "space": 0x20,
}
_DOWN = 0x8000


def key_code(name: str) -> int | None:
    """The virtual-key code for a key name such as "`", "mouse4", "f8" or "v". None if unknown."""
    key = name.strip().lower()
    if key in _NAMED_KEYS:
        return _NAMED_KEYS[key]
    if len(key) == 1 and key.isalnum():
        return ord(key.upper())
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return 0x6F + int(key[1:])
    return None


def _windows_key_down(code: int) -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(code) & _DOWN)  # type: ignore[attr-defined]


class PushToTalk:
    def __init__(self, key: str, key_down: Callable[[int], bool] | None = None) -> None:
        self.key = key
        self._code = key_code(key)
        if key_down is None and sys.platform == "win32":
            key_down = _windows_key_down
        self._key_down = key_down
        self._warned = False

    def held(self) -> bool:
        if self._code is None or self._key_down is None:
            if not self._warned:
                self._warned = True
                why = "it isn't a key name" if self._code is None else "it only works on Windows"
                log.warning("Push to talk can't read %r (%s): the mic stays muted", self.key, why)
            return False
        try:
            return self._key_down(self._code)
        except OSError:
            log.exception("Couldn't read the push-to-talk key; treating it as up")
            return False


def echo_window(
    bot_speaking: bool, stopped_at: float | None, tail_s: float, now: float | None = None
) -> bool:
    """While the partner talks, and for tail_s after: the speakers and the room still ring."""
    now = time.monotonic() if now is None else now
    return bot_speaking or (stopped_at is not None and now - stopped_at < tail_s)


class ModeLog:
    """Logs once when no headphones or push to talk is switched, as the mic frames read them."""

    def __init__(self, no_headphones: bool = False) -> None:
        self._no_headphones = no_headphones
        self._push_to_talk = False

    def note(self, no_headphones: bool, push_to_talk: bool, key: str) -> None:
        if no_headphones != self._no_headphones:
            self._no_headphones = no_headphones
            state = "on" if no_headphones else "off"
            log.info("No headphones %s: mic muted while the partner talks", state)
        if push_to_talk != self._push_to_talk:
            self._push_to_talk = push_to_talk
            log.info("Push to talk %s", f"on: hold {key} to speak" if push_to_talk else "off")
