"""Disk work for recordings, on one background thread, so encoding and writes never touch the loop.

Also the message log, which is the same idea for one file.
"""

import asyncio
import logging
import threading
import time
import wave
from collections import deque
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import BinaryIO, TextIO

from brain.replay.format import MessageRecord, jsonl_line
from shared.protocol import BrainMessage

log = logging.getLogger(__name__)

JOIN_TIMEOUT_S = 5.0

# The return value is ignored, so a job can be any call, such as a file opener.
Job = Callable[[], object]


class WriterThread:
    """Runs queued jobs in order on one daemon thread.

    Jobs are never dropped: lines and audio are small, and losing them would make a replay lie.
    Frames go in their own lane, capped at `max_frames`, that drops its oldest, because a recording
    must never hold back capture or grow without bound. Thread-safe, so hooks can call it from
    any thread.
    """

    def __init__(self, name: str, max_frames: int = 32) -> None:
        self._name = name
        self._max_frames = max_frames
        self._cond = threading.Condition()
        self._jobs: deque[tuple[str, Job]] = deque()
        self._frames: deque[Job] = deque()
        self._final: Job | None = None
        self._closing = False
        self._started = False
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        # Failures per kind of work, so a full disk logs once with its traceback, not every frame.
        self._failures: dict[str, int] = {}
        self.dropped = 0

    def start(self) -> None:
        self._started = True
        self._thread.start()

    def submit(self, what: str, job: Job) -> None:
        """`what` names the work for the log, such as "write an event"."""
        with self._cond:
            if self._closing:
                log.debug("%s is closed; not queueing: %s", self._name, what)
                return
            self._jobs.append((what, job))
            self._cond.notify()

    def submit_frame(self, job: Job) -> bool:
        """False if the oldest waiting frame was dropped to make room."""
        with self._cond:
            if self._closing:
                return True
            dropped = len(self._frames) >= self._max_frames
            if dropped:
                self._frames.popleft()
                self.dropped += 1
            self._frames.append(job)
            self._cond.notify()
        return not dropped

    async def stop(self, final: Job | None = None) -> bool:
        """Finishes what's queued, then runs `final`. False if it didn't finish in time.

        If this await is itself cancelled, it waits for the thread anyway, blocking, so a shutdown
        doesn't cut the session short, and then lets the cancellation through.
        """
        with self._cond:
            self._closing = True
            self._final = final
            self._cond.notify()
        if not self._started:
            return True
        try:
            await asyncio.to_thread(self._thread.join, JOIN_TIMEOUT_S)
        except asyncio.CancelledError:
            self._thread.join(JOIN_TIMEOUT_S)
            raise
        if self._thread.is_alive():
            log.warning(
                "%s didn't finish within %.0f s; the end may be lost", self._name, JOIN_TIMEOUT_S
            )
            return False
        return True

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._jobs and not self._frames and not self._closing:
                    self._cond.wait()
                if self._jobs:
                    what, job = self._jobs.popleft()
                elif self._frames:
                    what, job = "save a frame", self._frames.popleft()
                else:
                    break
            self._safely(what, job)
        if self._final is not None:
            self._safely("finish", self._final)
        for what, count in self._failures.items():
            log.warning("%s: %d attempts to %s failed in all", self._name, count, what)

    def _safely(self, what: str, job: Job) -> None:
        """A failed write must never take the brain down, so it's logged and the thread goes on."""
        try:
            job()
        except Exception:
            count = self._failures.get(what, 0) + 1
            self._failures[what] = count
            if count == 1:
                log.exception("%s could not %s; carrying on", self._name, what)
            else:
                log.debug("%s could not %s again (%d times)", self._name, what, count)


class LineFiles:
    """Text files opened on first use and flushed after every line, so a crash loses at most the
    line being written, which readers skip. Only the writer thread touches them."""

    def __init__(self) -> None:
        self._open: dict[Path, TextIO] = {}

    def open(self, path: Path) -> TextIO:
        """Truncates an existing file: each run writes its own."""
        handle = self._open.get(path)
        if handle is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.open("w", encoding="utf-8", newline="\n")
            self._open[path] = handle
        return handle

    def append(self, path: Path, line: str) -> None:
        handle = self.open(path)
        handle.write(line)
        handle.flush()

    def close(self) -> None:
        for path, handle in self._open.items():
            try:
                handle.close()
            except OSError:
                log.exception("Could not close %s", path)
        self._open.clear()


class WavAppender:
    """16-bit mono, opened on the first chunk. `wave` patches the header's sizes on every write, so
    flushing after each chunk leaves a playable file even after a crash."""

    def __init__(self, path: Path, sample_rate: int) -> None:
        self._path = path
        self._sample_rate = sample_rate
        self._file: BinaryIO | None = None
        self._wav: wave.Wave_write | None = None

    @property
    def opened(self) -> bool:
        return self._wav is not None

    def append(self, pcm: bytes) -> None:
        if self._wav is None or self._file is None:
            self._file = self._path.open("wb")
            self._wav = wave.open(self._file, "wb")
            self._wav.setnchannels(1)
            self._wav.setsampwidth(2)
            self._wav.setframerate(self._sample_rate)
        self._wav.writeframes(pcm)
        self._file.flush()

    def close(self) -> None:
        # wave doesn't close a file object it was handed, so both are closed here.
        try:
            if self._wav is not None:
                self._wav.close()
        finally:
            if self._file is not None:
                self._file.close()
            self._wav = None
            self._file = None


class MessageLog:
    """Writes every BrainMessage sent to one JSONL file, for `--write-messages` on a replay run."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.monotonic) -> None:
        self._path = path
        self._clock = clock
        self._t0 = clock()
        self._writer = WriterThread("Message log")
        self._files = LineFiles()

    def on_message(self, message: BrainMessage) -> None:
        try:
            t = rounded(self._clock() - self._t0)
            line = jsonl_line(MessageRecord(t=t, message=message.model_dump(mode="json")))
        except Exception:
            log.exception("Could not log a %s message", type(message).__name__)
            return
        self._writer.submit("write a message", partial(self._files.append, self._path, line))

    async def run(self) -> None:
        """Runs until cancelled, then flushes and closes the file."""
        # Opened at once, so a run that sends nothing still replaces an older file.
        self._writer.submit("open the message log", partial(self._files.open, self._path))
        self._writer.start()
        log.info("Writing sent messages to %s", self._path)
        try:
            await asyncio.Event().wait()
        finally:
            await self._writer.stop(self._files.close)


def rounded(t: float) -> float:
    """A tenth of a millisecond is finer than anything replay can act on, and keeps files short."""
    return round(t, 4)
