"""One log line per Claude call: time to first token and tokens used, cached or not.

scripts/latency_report.py parses the line, so keep its format in step with USAGE_LINE there.
"""

import logging
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)


class CallTimer:
    """Starts when made. For a streamed call, the first token is the first text, which is when
    speech can start; for a call that isn't streamed, it's the whole call."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._start = clock()
        self._first: float | None = None

    def first_token(self) -> None:
        if self._first is None:
            self._first = self._clock()

    def ttft_ms(self) -> int:
        end = self._first if self._first is not None else self._clock()
        return round((end - self._start) * 1000)


def _count(usage: object, name: str) -> int:
    # The API leaves cache fields out or None when nothing was cached, and test fakes have none.
    value = getattr(usage, name, None)
    return value if isinstance(value, int) else 0


def log_usage(role: str, model: str, timer: CallTimer, message: Any) -> None:
    """`message` is the response, or a stream's snapshot so far; either may lack usage."""
    usage = getattr(message, "usage", None)
    log.info(
        "LLM usage: role=%s model=%s ttft_ms=%d input=%d cache_read=%d cache_write=%d output=%d",
        role,
        model,
        timer.ttft_ms(),
        _count(usage, "input_tokens"),
        _count(usage, "cache_read_input_tokens"),
        _count(usage, "cache_creation_input_tokens"),
        _count(usage, "output_tokens"),
    )


def stream_snapshot(stream: Any) -> Any:
    """What a stream has received so far. The SDK asserts before its first event arrives."""
    try:
        return stream.current_message_snapshot
    except (AttributeError, AssertionError):
        return None
