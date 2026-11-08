"""Spots a player turn that is really the partner's own voice, heard back through the mic.

Without headphones, speech-to-text hears the speakers and the partner answers itself, over and
over, until the talker's rate limit runs out. That happened in a live test. The mic can't tell
voices apart, so this compares words: a turn made mostly of words the partner said a moment ago,
in the same order, is dropped. Deterministic, so it's testable and needs no model.
"""

import re
import time
from collections import deque
from collections.abc import Callable
from difflib import SequenceMatcher

# How long after saying something its echo can still arrive: a long line takes a while to play,
# and the final transcript lands after the speech ends.
ECHO_WINDOW_S = 20.0
# Share of the turn's words found, in order, in one recent partner line.
ECHO_SHARE = 0.7
# Shorter turns, such as "yeah" or "what's that", are too short to judge and always go through.
MIN_WORDS = 3
MAX_LINES = 10

_WORD = re.compile(r"[a-z0-9']+")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.casefold().replace("’", "'"))


class SelfEcho:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._said: deque[tuple[float, list[str]]] = deque(maxlen=MAX_LINES)

    def said(self, text: str) -> None:
        words = _words(text)
        if words:
            self._said.append((self._clock(), words))

    def is_echo(self, transcript: str) -> bool:
        heard = _words(transcript)
        if len(heard) < MIN_WORDS:
            return False
        now = self._clock()
        for at, line in self._said:
            if now - at > ECHO_WINDOW_S:
                continue
            blocks = SequenceMatcher(None, heard, line, autojunk=False).get_matching_blocks()
            if sum(block.size for block in blocks) / len(heard) >= ECHO_SHARE:
                return True
        return False
