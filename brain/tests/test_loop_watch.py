"""The loop watch is the proof that nothing blocks the event loop, so it must catch a real block."""

import asyncio
import logging
import time

import pytest

from brain.loop_watch import WARN_MS, watch_loop

LOGGER = "brain.loop_watch"


def stall_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == LOGGER and record.msg == "Event loop stalled %.0f ms"
    ]


def summaries(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == LOGGER and record.msg == "Event loop: longest stall %.0f ms over %.0f s"
    ]


async def stop(watch: asyncio.Task[None]) -> None:
    watch.cancel()
    with pytest.raises(asyncio.CancelledError):
        await watch


async def test_blocking_the_loop_is_warned_and_recorded(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    watch = asyncio.create_task(watch_loop())
    await asyncio.sleep(0)  # The watch is now waiting out its first interval.
    time.sleep(0.3)  # noqa: ASYNC251 - the kind of sync call the never-block rule forbids.
    await asyncio.sleep(0.1)
    await stop(watch)

    # About 250 ms: the block less the interval it was due to wait anyway, with slack because
    # asyncio can wake a timer up to one clock tick (about 16 ms on Windows) early.
    warnings = stall_warnings(caplog)
    assert len(warnings) == 1
    assert warnings[0].levelno == logging.WARNING
    assert warnings[0].args is not None and warnings[0].args[0] >= 220
    (summary,) = summaries(caplog)
    assert summary.args is not None and summary.args[0] == warnings[0].args[0]


async def test_an_idle_loop_logs_no_stall(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    watch = asyncio.create_task(watch_loop())
    await asyncio.sleep(0.3)
    await stop(watch)

    assert not stall_warnings(caplog)
    (summary,) = summaries(caplog)
    assert summary.args is not None and summary.args[0] < WARN_MS


async def test_cancelling_logs_the_summary_and_still_cancels(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    watch = asyncio.create_task(watch_loop())
    await asyncio.sleep(0.12)
    await stop(watch)

    (summary,) = summaries(caplog)
    assert summary.levelno == logging.INFO
    assert summary.args is not None
    watched_s = summary.args[1]
    assert isinstance(watched_s, float) and 0.1 <= watched_s < 1.0
    assert summary.getMessage().startswith("Event loop: longest stall ")
