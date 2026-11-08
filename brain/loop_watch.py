"""Measure event-loop wakeup delays during live play and replay."""

import asyncio
import logging

log = logging.getLogger(__name__)


async def watch_loop(interval: float = 0.05, threshold: float = 0.1) -> None:
    clock = asyncio.get_running_loop().time
    longest = 0.0
    try:
        while True:
            due = clock() + interval
            await asyncio.sleep(interval)
            late = clock() - due
            longest = max(longest, late)
            if late > threshold:
                log.warning("Event loop: stall %.0f ms", late * 1000)
    finally:
        log.info("Event loop: longest stall %.0f ms", longest * 1000)
