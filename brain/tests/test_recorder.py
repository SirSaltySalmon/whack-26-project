import asyncio
import logging
import threading
import wave
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from brain.capture.ring_buffer import Frame, RingBuffer
from brain.events import EventBus, GameEvent, OverlayConnected, PlayerSpeech, Tick
from brain.perception.coords import CropRegion
from brain.replay import format as fmt
from brain.replay import recorder as recorder_module
from brain.replay.recorder import MessageLog, SessionRecorder
from brain.tests.fakes import make_frame
from shared.protocol import BrainMessageAdapter
from shared.protocol.messages import PointerHide, Rect, Settings, SubtitleChunk

T0 = 100.0
FPS = 50  # Polls every 20 ms, so tests don't wait long for a frame to be noticed
NOW = datetime(2026, 11, 8, 1, 23, 45, 678)


class WatchedBuffer(RingBuffer):
    """Counts reads, so a test can wait until the recorder has looked at a frame."""

    def __init__(self) -> None:
        super().__init__(4)
        self.reads = 0

    def latest(self) -> Frame | None:
        self.reads += 1
        return super().latest()


async def wait_until(condition: Callable[[], bool]) -> None:
    """Polls, because what it waits for happens on the writer thread or at the next timed poll."""
    for _ in range(600):
        if condition():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("Timed out waiting")


async def cancel(task: "asyncio.Task[None]") -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


class Rig:
    def __init__(self, root: Path, max_gb: float = 1.0, settings: Settings | None = None) -> None:
        self.buffer = WatchedBuffer()
        self.bus = EventBus()
        self.now = T0  # What the recorder's clock reads
        self.scale = 1.0
        self.recorder = SessionRecorder(
            root,
            "Test Game",
            self.buffer,
            self.bus,
            lambda: self.scale,
            FPS,
            max_gb,
            settings=(lambda: settings) if settings else None,
            clock=lambda: self.now,
            now=lambda: NOW,
        )
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> Path:
        self.task = asyncio.create_task(self.recorder.run())
        await wait_until(lambda: self.recorder.session_dir is not None)
        assert self.recorder.session_dir is not None
        return self.recorder.session_dir

    async def push(self, ts: float, **frame: Any) -> None:
        """Returns once the recorder has polled the buffer after the push."""
        self.buffer.push(make_frame(ts=ts, **{"width": 64, "height": 36, **frame}))
        seen = self.buffer.reads
        await wait_until(lambda: self.buffer.reads > seen)

    async def stop(self) -> None:
        assert self.task is not None
        await cancel(self.task)


def frames_in(directory: Path) -> list[fmt.FrameRecord]:
    return fmt.read_jsonl(directory / fmt.FRAMES, fmt.FrameRecord)


def events_in(directory: Path) -> list[fmt.EventRecord]:
    return fmt.read_jsonl(directory / fmt.EVENTS, fmt.EventRecord)


async def test_a_recorded_session_reads_back_for_replay(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    pcm = np.arange(-800, 800, dtype=np.int16).tobytes()
    subtitle = SubtitleChunk(utterance_id="u1", text="Hi there.", final=True)
    # The hooks may run before run() starts, so their work waits for the session to exist.
    rig.recorder.on_mic_audio(pcm)
    rig.recorder.on_message(subtitle)
    directory = await rig.start()
    ramp = np.tile(np.linspace(0, 255, 64, dtype=np.uint8), (36, 1))
    image = np.stack([ramp, ramp[::-1], np.full_like(ramp, 90)], axis=2)
    rect = Rect(x=1, y=2, width=30, height=40)
    await rig.push(99.0)  # From before the recording started, so skipped
    await rig.push(101.5, image=image, region=CropRegion(10, 20, 64, 36), rects=[rect])
    await wait_until(lambda: len(frames_in(directory)) == 1)  # Polled again meanwhile
    await rig.push(102.0, fill=200)
    rig.bus.publish(PlayerSpeech("what's that?", ts=102.5))
    rig.now = 103.0
    rig.recorder.on_message(PointerHide())
    rig.recorder.on_mic_audio(pcm)
    await rig.stop()

    first, second = frames_in(directory)
    assert (first.seq, first.t, first.file) == (1, 1.5, "frames/000001.jpg")
    assert (second.seq, second.t, second.file) == (2, 2.0, "frames/000002.jpg")
    assert first.region == fmt.RegionRecord(x=10, y=20, width=64, height=36)
    assert first.overlay_rects == [rect]
    assert second.region is None and second.overlay_rects == []
    decoded = fmt.decode_frame((directory / first.file).read_bytes())
    assert decoded.shape == image.shape
    assert np.abs(decoded.astype(int) - image.astype(int)).max() <= 8
    (event,) = events_in(directory)
    replayed = fmt.replay_event(event)
    assert event.t == 2.5 and isinstance(replayed, PlayerSpeech)
    assert replayed.transcript == "what's that?"
    messages = fmt.read_jsonl(directory / fmt.MESSAGES, fmt.MessageRecord)
    sent = [(r.t, r.message["type"]) for r in messages]
    assert sent == [(0, "subtitle.chunk"), (3, "pointer.hide")]
    assert BrainMessageAdapter.validate_python(messages[0].message) == subtitle
    with wave.open(str(directory / fmt.AUDIO), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 16000)
        assert wav.readframes(wav.getnframes()) == pcm * 2
    assert fmt.read_manifest(directory).has_audio


async def test_events_are_recorded_relative_to_the_start(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.bus.publish(PlayerSpeech("hello", ts=101.0))  # Before run(): the bus is already watched
    directory = await rig.start()
    rig.bus.publish(GameEvent("hp_low", {"value": 20}, source="reader", ts=102.0))
    rig.bus.publish(OverlayConnected(1.0, ts=102.5))
    rig.bus.publish(Tick(ts=103.0))
    rig.bus.publish(GameEvent("danger_started", {"threats": ["Slime"]}, ts=103.5))
    rig.now = 104.25
    rig.recorder.on_partner_said("That looks rough.")
    await rig.stop()

    records = events_in(directory)
    kinds = ["PlayerSpeech", "GameEvent", "GameEvent", "PartnerSaid"]
    assert [(r.t, r.kind) for r in records] == list(zip([1.0, 2.0, 3.5, 4.25], kinds, strict=True))
    assert records[1].data["source"] == "reader"
    assert records[3].data == {"text": "That looks rough."}


async def test_the_manifest_is_completed_when_recording_stops(tmp_path: Path) -> None:
    settings = Settings(personality="snarky", voice_id="v1")
    (tmp_path / "20261108-012345-test-game").mkdir()  # A session started in the same second
    rig = Rig(tmp_path, settings=settings)
    directory = await rig.start()
    assert directory == tmp_path / "20261108-012345-test-game-2"
    started = fmt.read_manifest(directory)
    assert not started.complete and started.created_at == "2026-11-08T01:23:45"
    assert (started.game, started.record_fps, started.display_scale) == ("Test Game", FPS, 1.0)
    assert started.settings == settings.model_dump(mode="json")

    rig.bus.publish(OverlayConnected(1.5))
    rig.bus.publish(PlayerSpeech("marker"))  # Written after the manifest, so it shows it's done
    await wait_until(lambda: len(events_in(directory)) == 1)
    rewritten = fmt.read_manifest(directory)
    assert rewritten.display_scale == 1.5 and not rewritten.complete

    rig.scale = 1.25
    rig.now = 112.5
    await rig.stop()
    finished = fmt.read_manifest(directory)
    assert finished.complete and finished.duration_s == 12.5 and finished.display_scale == 1.25
    assert finished.dropped_frames == 0 and not finished.has_audio
    assert finished.settings == settings.model_dump(mode="json")
    assert not (directory / fmt.AUDIO).exists()


async def test_a_slow_writer_drops_the_oldest_frames_without_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(recorder_module, "MAX_QUEUED_FRAMES", 3)
    entered, release = threading.Event(), threading.Event()
    real_encode = recorder_module.encode_frame

    def stuck_encode(image: np.ndarray, quality: int = 90) -> bytes:
        entered.set()
        release.wait(5)
        return real_encode(image, quality)

    monkeypatch.setattr(recorder_module, "encode_frame", stuck_encode)
    rig = Rig(tmp_path)
    directory = await rig.start()
    try:
        await rig.push(101.0)
        await wait_until(entered.is_set)
        # The writer is stuck on the first frame, yet each push is still picked up at once.
        for ts in range(102, 109):
            await rig.push(float(ts))
    finally:
        release.set()
    await rig.stop()

    assert [record.t for record in frames_in(directory)] == [1.0, 6.0, 7.0, 8.0]
    assert fmt.read_manifest(directory).dropped_frames == 4


async def test_frames_stop_at_the_disk_cap_while_events_go_on(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger=recorder_module.__name__)
    rig = Rig(tmp_path, max_gb=1e-9)  # One byte: the first frame passes it
    directory = await rig.start()
    for ts in (101.0, 102.0, 103.0):
        await rig.push(ts)
        await wait_until(lambda: len(frames_in(directory)) == 1)
    rig.bus.publish(PlayerSpeech("still listening", ts=104.0))
    await rig.stop()

    assert [record.t for record in frames_in(directory)] == [1.0]
    assert len(list((directory / "frames").iterdir())) == 1
    assert [record.kind for record in events_in(directory)] == ["PlayerSpeech"]
    assert len([r for r in caplog.records if "GB limit" in r.getMessage()]) == 1


async def test_a_failed_write_is_logged_and_recording_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    real_encode = recorder_module.encode_frame
    calls: list[int] = []

    def flaky_encode(image: np.ndarray, quality: int = 90) -> bytes:
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("boom")
        return real_encode(image, quality)

    monkeypatch.setattr(recorder_module, "encode_frame", flaky_encode)
    rig = Rig(tmp_path)
    directory = await rig.start()
    await rig.push(101.0)
    await wait_until(lambda: len(calls) == 1)
    await rig.push(102.0)
    await rig.stop()
    assert [(record.seq, record.t) for record in frames_in(directory)] == [(1, 2.0)]
    assert "could not save a frame" in caplog.text and "boom" in caplog.text
    assert fmt.read_manifest(directory).complete


async def test_a_folder_that_cant_be_made_doesnt_stop_the_brain(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "taken"
    root.write_text("a file, not a folder", encoding="utf-8")
    rig = Rig(root)
    task = asyncio.create_task(rig.recorder.run())
    await wait_until(lambda: "Could not start recording" in caplog.text)
    for number in range(300):  # More than the bus queue holds, which would warn on each drop
        rig.bus.publish(PlayerSpeech(f"line {number}"))
        await asyncio.sleep(0)
    assert not task.done() and rig.recorder.session_dir is None
    assert "Event queue full" not in caplog.text
    await cancel(task)


async def test_the_message_log_replaces_an_older_file(tmp_path: Path) -> None:
    path = tmp_path / "out" / "messages.jsonl"
    path.parent.mkdir()
    path.write_text("an older run's line\n", encoding="utf-8")
    now = [T0]
    message_log = MessageLog(path, clock=lambda: now[0])
    message_log.on_message(SubtitleChunk(utterance_id="u1", text="Hi."))
    task = asyncio.create_task(message_log.run())
    now[0] = T0 + 2.0
    message_log.on_message(PointerHide())
    await asyncio.sleep(0)
    await cancel(task)
    sent = [(r.t, r.message["type"]) for r in fmt.read_jsonl(path, fmt.MessageRecord)]
    assert sent == [(0, "subtitle.chunk"), (2, "pointer.hide")]
    assert "older" not in path.read_text(encoding="utf-8")

    # A run that sends nothing still leaves an empty file, not the last run's.
    task = asyncio.create_task(MessageLog(path).run())
    await asyncio.sleep(0)
    await cancel(task)
    assert path.read_text(encoding="utf-8") == ""
