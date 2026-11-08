"""Spots a player turn that is really the partner's own voice, heard back through the mic.

Without headphones, speech-to-text hears the speakers and the partner answers itself, over and
over, until the talker's rate limit runs out. That happened in a live test. The mic can't tell
voices apart, so this compares words: a turn made mostly of words the partner said a moment ago,
in the same order, is dropped. Deterministic, so it's testable and needs no model. Speech-to-text
is English (Flux), so the word lists below are English.
"""

import re
import time
from collections import deque
from collections.abc import Callable

# How long after saying something its echo can still arrive: a long line takes a while to play,
# and the final transcript lands after the speech ends.
ECHO_WINDOW_S = 20.0
# Share of the turn's words found, in order, in one recent partner line.
ECHO_SHARE = 0.7
# Below this many words a partial match proves nothing, so only a whole line repeated counts.
MIN_WORDS = 3
MAX_LINES = 10

_WORD = re.compile(r"[a-z0-9']+")
# Speech-to-text writes contractions either way ("I'll" or "I will"), so both sides are expanded.
_CONTRACTIONS = {
    "can't": "can not",
    "won't": "will not",
    "shan't": "shall not",
    "let's": "let us",
    "i'm": "i am",
}
_SUFFIXES = (("n't", " not"), ("'ll", " will"), ("'re", " are"), ("'ve", " have"), ("'d", " would"))
# A turn that differs from the partner's line by one of these words says something else, as in
# "Don't use the potion" after "Use the potion", so it's never taken for an echo.
_NEGATIONS = frozenset({"not", "no", "never", "nope", "nothing", "none", "nor"})


def _expand(word: str) -> str:
    if word in _CONTRACTIONS:
        return _CONTRACTIONS[word]
    for suffix, replacement in _SUFFIXES:
        if word.endswith(suffix) and len(word) > len(suffix):
            return word[: -len(suffix)] + replacement
    # "it's" and "that's" are "is"; a possessive's "s" stays attached and still matches itself.
    return word.removesuffix("'s") + " is" if word in {"it's", "that's", "what's"} else word


def _words(text: str) -> list[str]:
    raw = _WORD.findall(text.casefold().replace("’", "'"))
    return " ".join(_expand(word) for word in raw).split()


def _matched(heard: list[str], line: list[str]) -> list[bool]:
    """Which heard words belong to the longest run of words shared in order with the line."""
    rows, cols = len(heard), len(line)
    best = [[0] * (cols + 1) for _ in range(rows + 1)]
    for i in range(rows - 1, -1, -1):
        for j in range(cols - 1, -1, -1):
            if heard[i] == line[j]:
                best[i][j] = best[i + 1][j + 1] + 1
            else:
                best[i][j] = max(best[i + 1][j], best[i][j + 1])
    matched = [False] * rows
    i = j = 0
    while i < rows and j < cols:
        if heard[i] == line[j]:
            matched[i] = True
            i, j = i + 1, j + 1
        elif best[i + 1][j] >= best[i][j + 1]:
            i += 1
        else:
            j += 1
    return matched


def _echoes(heard: list[str], line: list[str]) -> bool:
    if len(heard) < MIN_WORDS:
        return heard == line
    matched = _matched(heard, line)
    if sum(matched) / len(heard) < ECHO_SHARE:
        return False
    extra = {word for word, hit in zip(heard, matched, strict=True) if not hit}
    return not extra & _NEGATIONS


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
        if not heard:
            return False
        now = self._clock()
        return any(_echoes(heard, line) for at, line in self._said if now - at <= ECHO_WINDOW_S)
