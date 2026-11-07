import numpy as np

from brain.capture.ring_buffer import Frame, RingBuffer


def frame(ts: float, value: int = 0) -> Frame:
    return Frame(ts, np.full((2, 2, 3), value, dtype=np.uint8))


def test_keeps_only_the_newest_frames() -> None:
    buffer = RingBuffer(2)
    for ts in (1.0, 2.0, 3.0):
        buffer.push(frame(ts))
    assert len(buffer) == 2
    latest = buffer.latest()
    assert latest is not None and latest.ts == 3.0


def test_nearest_finds_the_closest_frame() -> None:
    buffer = RingBuffer(5)
    for ts in (1.0, 2.0, 3.0):
        buffer.push(frame(ts))
    nearest = buffer.nearest(2.2)
    assert nearest is not None and nearest.ts == 2.0
    assert RingBuffer(1).nearest(1.0) is None


def test_push_copies_so_capture_cannot_overwrite_history() -> None:
    buffer = RingBuffer(1)
    source = frame(1.0, 7)
    buffer.push(source)
    source.image[:] = 99
    latest = buffer.latest()
    assert latest is not None and latest.image.max() == 7
