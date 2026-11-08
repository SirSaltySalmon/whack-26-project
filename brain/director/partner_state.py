"""What the partner itself said lately: its last question and its tips, shown to it as YOU.

Kept by code in RAM from lines really said, so it costs no model call and can't misremember what
was spoken. It lives as long as the director does, which is one session. The conversation history
holds the same lines, but a model reading a long history still asked a question twice and repeated
tips, so the few lines that cause that are pulled out where it can't miss them, with their ages.
"""

from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

YOU_LABEL = "YOU"
MAX_TIPS = 5
# LIVE comes on every call and isn't cached, so this stays a few lines long.
MAX_CHARS = 600
# Past this the question belongs to an earlier moment, and showing it would invite an answer to it.
QUESTION_MAX_AGE_S = 600.0
_QUESTION_CHARS = 200
_TIP_CHARS = 140
_ELLIPSIS = "…"


@dataclass(frozen=True)
class _Line:
    text: str
    at: float


def _clean(text: str) -> str:
    return " ".join(text.split())


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = text[: max(limit - 1, 0)]
    boundary = head.rfind(" ")
    if boundary >= limit // 2:
        head = head[:boundary]
    return head.rstrip(" ,;:") + _ELLIPSIS


def age(seconds: float) -> str:
    """Ages read like speech, because the model compares them, not computes with them."""
    if seconds < 1:
        return "just now"
    if seconds < 60:
        return f"{int(seconds)} s ago"
    if seconds < 3600:
        return f"{round(seconds / 60)} min ago"
    return f"{round(seconds / 3600)} h ago"


class PartnerState:
    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._question: _Line | None = None
        self._replied = False
        self._tips: deque[_Line] = deque(maxlen=MAX_TIPS)

    def spoke(self, text: str) -> None:
        """Every line really said. A question is any line ending in "?", as the rules count one."""
        if text.rstrip().endswith("?"):
            self._question = _Line(_shorten(_clean(text), _QUESTION_CHARS), self._clock())
            self._replied = False

    def tipped(self, text: str) -> None:
        """A tip that was really said."""
        self._tips.append(_Line(_shorten(_clean(text), _TIP_CHARS), self._clock()))

    @contextmanager
    def replying(self) -> Iterator[None]:
        """Wraps a player turn. Once it's over, even cut short, they've had their say since the
        question before it. A question asked in the turn's own reply is still waiting."""
        asked = self._question
        try:
            yield
        finally:
            if asked is not None and self._question is asked:
                self._replied = True

    def render(self) -> str:
        """The YOU section's text, or "" when there's nothing to say."""
        now = self._clock()
        question = ""
        if self._question is not None and now - self._question.at <= QUESTION_MAX_AGE_S:
            # "Before now" reads right both while their words are being answered, which may be the
            # answer, and in a tip or a reaction, where it's still waiting.
            status = "they've replied since" if self._replied else "not answered before now"
            question = (
                f"your last question ({age(now - self._question.at)}, {status}): "
                f'"{self._question.text}"'
            )
        tips = [f'"{tip.text}" ({age(now - tip.at)})' for tip in reversed(self._tips)]
        text = _join(question, tips)
        # The oldest tips go first: the newest is the one most likely to be repeated.
        while len(text) > MAX_CHARS and tips:
            tips.pop()
            text = _join(question, tips)
        return text if len(text) <= MAX_CHARS else _shorten(text, MAX_CHARS)


def _join(question: str, tips: list[str]) -> str:
    parts = [question] if question else []
    if tips:
        parts.append("tips you gave, newest first: " + "; ".join(tips))
    return ". ".join(parts)
