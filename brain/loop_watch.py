"""Measures how late the event loop wakes, so a saved log proves the never-block rule.

A sync call on the loop (CV, OCR, a blocking SDK) delays every timer, including this one, so a
late wake-up is a stall that held up speech and barks too. scripts/latency_report.py counts the
lines logged here.
"""

import asyncio
import logging
import time

log = logging.getLogger(__name__)

INTERVAL_S = 0.05
# A starting value: Windows timers alone can wake about 16 ms late, while a 100 ms stall already
# eats a third of the 300 ms bark budget.
WARN_MS = 100.0


async def watch_loop(interval_s: float = INTERVAL_S, warn_ms: float = WARN_MS) -> None:
    """Runs until cancelled, warning on each stall and logging the longest one when it stops."""
    started = time.monotonic()
    longest_ms = 0.0
    try:
        while True:
            before = time.monotonic()
            await asyncio.sleep(interval_s)
            late_ms = (time.monotonic() - before - interval_s) * 1000
            longest_ms = max(longest_ms, late_ms)
            if late_ms > warn_ms:
                log.warning("Event loop stalled %.0f ms", late_ms)
    finally:
        # The brain's TaskGroup cancels this at shutdown, so the summary ends the log.
        log.info(
            "Event loop: longest stall %.0f ms over %.0f s",
            longest_ms,
            time.monotonic() - started,
        )
