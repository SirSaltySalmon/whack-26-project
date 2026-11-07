"""Frame sources. Each returns BGR arrays in physical pixels, or None when nothing is new."""

import logging
from typing import Any, Protocol

import numpy as np

log = logging.getLogger(__name__)


class FrameSource(Protocol):
    def start(self) -> None: ...
    def grab(self) -> np.ndarray | None: ...
    def stop(self) -> None: ...


class DxcamSource:
    """Fast DXGI capture of one monitor. A None from grab() just means a still screen."""

    def __init__(self, output_idx: int = 0) -> None:
        self._output_idx = output_idx
        self._camera: Any = None  # dxcam ships no type stubs.

    def start(self) -> None:
        import dxcam

        self._camera = dxcam.create(output_idx=self._output_idx, output_color="BGR")

    def grab(self) -> np.ndarray | None:
        return self._camera.grab() if self._camera else None

    def stop(self) -> None:
        if self._camera:
            self._camera.release()
            self._camera = None


class MssSource:
    """Slower fallback when DXGI capture isn't available."""

    def __init__(self, monitor_idx: int = 1) -> None:
        self._monitor_idx = monitor_idx
        self._sct: Any = None  # The mss factory's return type varies by platform.

    def start(self) -> None:
        import mss

        self._sct = mss.mss()

    def grab(self) -> np.ndarray | None:
        if self._sct is None:
            return None
        shot = self._sct.grab(self._sct.monitors[self._monitor_idx])
        return np.asarray(shot)[:, :, :3]  # BGRA to BGR

    def stop(self) -> None:
        if self._sct:
            self._sct.close()
            self._sct = None


class FallbackSource:
    """Uses dxcam, dropping to mss if dxcam can't start on this machine."""

    def __init__(self) -> None:
        self._active: FrameSource = DxcamSource()

    def start(self) -> None:
        try:
            self._active.start()
        except Exception:
            log.exception("dxcam failed to start; falling back to mss")
            self._active = MssSource()
            self._active.start()

    def grab(self) -> np.ndarray | None:
        return self._active.grab()

    def stop(self) -> None:
        self._active.stop()


def default_live_source() -> FrameSource:
    return FallbackSource()
