import numpy as np

from brain.capture.loop import CaptureLoop
from brain.capture.ring_buffer import Frame, RingBuffer
from brain.capture.window import crop_to_region
from brain.perception.coords import CropRegion
from shared.protocol.messages import Rect

REGION = CropRegion(10, 20, 30, 40)


class FakeSource:
    def __init__(self, image: np.ndarray | None, error: Exception | None = None) -> None:
        self.image = image
        self.error = error
        self.grabs = 0

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def grab(self) -> np.ndarray | None:
        self.grabs += 1
        if self.error:
            raise self.error
        return self.image


class FakeWindow:
    """Answers each visible_region call in turn, repeating the last answer."""

    def __init__(self, *answers: CropRegion | None) -> None:
        self.answers = list(answers)

    def visible_region(self) -> CropRegion | None:
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class NoOverlay:
    rects: tuple[Rect, ...] = ()


def screen() -> np.ndarray:
    """Each pixel's value identifies its row, so a test can tell which part it got."""
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    image[:, :, 0] = np.arange(100, dtype=np.uint8)[:, np.newaxis]
    return image


def loop_with(source: FakeSource, window: FakeWindow | None) -> CaptureLoop:
    return CaptureLoop(source, RingBuffer(1), NoOverlay(), 2, window)


def test_crop_clips_to_the_screen_and_reports_the_real_area() -> None:
    cropped = crop_to_region(screen(), CropRegion(-10, 90, 50, 50))
    assert cropped is not None
    assert cropped[0].shape[:2] == (10, 40)
    assert cropped[1] == CropRegion(0, 90, 40, 10)


def test_crop_of_a_window_off_screen_is_none() -> None:
    assert crop_to_region(screen(), CropRegion(500, 500, 50, 50)) is None


def test_frame_holds_only_the_game_window() -> None:
    frame = loop_with(FakeSource(screen()), FakeWindow(REGION))._capture(())
    assert frame is not None
    assert frame.image.shape[:2] == (40, 30)
    assert frame.image[0, 0, 0] == 20
    assert frame.region == REGION


def test_nothing_is_grabbed_while_the_game_is_not_in_front() -> None:
    source = FakeSource(screen())
    assert loop_with(source, FakeWindow(None))._capture(()) is None
    assert source.grabs == 0


def test_frame_is_dropped_if_the_player_alt_tabs_during_the_grab() -> None:
    assert loop_with(FakeSource(screen()), FakeWindow(REGION, None))._capture(()) is None


def test_frame_is_dropped_if_the_window_moves_during_the_grab() -> None:
    moved = CropRegion(0, 0, 30, 40)
    assert loop_with(FakeSource(screen()), FakeWindow(REGION, moved))._capture(()) is None


def test_still_screen_produces_no_frame() -> None:
    assert loop_with(FakeSource(None), FakeWindow(REGION))._capture(()) is None


def test_capture_error_does_not_escape_and_recovers() -> None:
    source = FakeSource(screen(), RuntimeError("display changed"))
    loop = loop_with(source, FakeWindow(REGION))
    assert loop._capture_safely(()) is None
    source.error = None
    assert loop._capture_safely(()) is not None


def test_ring_buffer_keeps_the_region() -> None:
    buffer = RingBuffer(1)
    buffer.push(Frame(1.0, screen(), (), REGION))
    latest = buffer.latest()
    assert latest is not None and latest.region == REGION
