"""Player turns typed on stdin, so a full turn can be tested with no mic or Deepgram key.

Each line becomes the same events real voice sends, so everything after this runs as it does live.
A prefix like `5: what's that` waits first, which leaves time to switch back to the game: capture
stops while the terminal is in front, and look_closer says it can't see once capture has been
stopped for too long.
"""

import asyncio
import logging
import re
import sys
import threading
from collections.abc import Callable

from brain.events import EventBus, PlayerSpeech, PlayerStartedSpeaking

log = logging.getLogger(__name__)

# Plenty of time to set anything up. A bigger number is more likely part of what was typed.
MAX_DELAY_S = 300.0

# The space after the colon is what keeps "12:30 is late" a plain sentence.
_DELAY_PREFIX = re.compile(r"(?P<delay>[0-9]+(?:\.[0-9]+)?):(?:\s+(?P<transcript>.*))?")


def parse_typed_line(line: str) -> tuple[float, str] | None:
    """Returns (delay_s, transcript), or None for a blank line. Pure, so it's easy to test."""
    text = line.strip()
    if not text:
        return None
    match = _DELAY_PREFIX.fullmatch(text)
    if match is None or float(match["delay"]) > MAX_DELAY_S:
        return 0.0, text
    transcript = match["transcript"]
    # A delay with nothing after it has no turn to start, so it counts as blank.
    return (float(match["delay"]), transcript) if transcript else None


def _read_lines(
    read_line: Callable[[], str],
    loop: asyncio.AbstractEventLoop,
    lines: "asyncio.Queue[str | None]",
    _stdin: object,
) -> None:
    """Runs on its own thread. Puts None on the queue when there's nothing more to read.

    `_stdin` only makes this frame keep sys.stdin alive. Before Python 3.12.10, input() doesn't hold
    a reference of its own, so with stdin or stdout redirected, shutdown closes stdin under a stuck
    read and the process dies with "Fatal Python error: _enter_buffered_busy".
    """
    line: str | None = ""
    while line is not None:
        try:
            line = read_line()
        except EOFError:
            log.info("End of typed input, so typed turns are finished")
            line = None
        except Exception:
            log.exception("Couldn't read a typed line, so typed turns are finished")
            line = None
        try:
            loop.call_soon_threadsafe(lines.put_nowait, line)
        except RuntimeError:
            # The brain stopped while this was waiting for input, so the loop is already closed.
            return


async def typed_turns(bus: EventBus, read_line: Callable[[], str] = input) -> None:
    """Runs read_line off the loop. Returns at end of input. Blank lines are ignored."""
    log.info("Typed turns are on: type a line, then Enter. '5: what's that' waits 5 s first.")
    lines: asyncio.Queue[str | None] = asyncio.Queue()
    # Not asyncio.to_thread: asyncio.run waits for its executor's threads on the way out, so a
    # thread stuck in input() would hold up Ctrl+C. A daemon thread can simply be left behind.
    threading.Thread(
        target=_read_lines,
        args=(read_line, asyncio.get_running_loop(), lines, sys.stdin),
        name="typed-turns",
        daemon=True,
    ).start()
    while (line := await lines.get()) is not None:
        parsed = parse_typed_line(line)
        if parsed is None:
            continue
        delay_s, transcript = parsed
        if delay_s > 0:
            log.info("Typed turn starts in %.1f s: %s", delay_s, transcript)
            await asyncio.sleep(delay_s)
        log.info("Player (typed): %s", transcript)
        bus.publish(PlayerStartedSpeaking())
        # Real voice never sends these together, so subscribers get a tick between them here too.
        await asyncio.sleep(0)
        bus.publish(PlayerSpeech(transcript=transcript))
