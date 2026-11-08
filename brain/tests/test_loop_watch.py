import asyncio
import logging
import re
import time

import pytest

from brain.loop_watch import watch_loop


@pytest.mark.asyncio
async def test_blocking_loop_reports_stall_and_maximum(caplog):
    caplog.set_level(logging.INFO, logger="brain.loop_watch")
    watch = asyncio.create_task(watch_loop(interval=0.01))
    await asyncio.sleep(0)
    try:
        time.sleep(0.2)  # noqa: ASYNC251 - deliberately stall the watched loop.
        await asyncio.sleep(0.03)
    finally:
        watch.cancel()
        with pytest.raises(asyncio.CancelledError):
            await watch
    stalls = [int(ms) for ms in re.findall(r"Event loop: stall (\d+) ms", caplog.text)]
    assert max(stalls) >= 150
    assert f"Event loop: longest stall {max(stalls)} ms" in caplog.text
