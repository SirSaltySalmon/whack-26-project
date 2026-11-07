"""Plays a recorded session through the same pipeline as live capture.

TODO(track 2): define the session format, add the recorder, and implement this source.
"""

from pathlib import Path

import numpy as np


class ReplayFrameSource:
    def __init__(self, session_dir: Path) -> None:
        self._session_dir = session_dir

    def start(self) -> None:
        raise NotImplementedError(f"Replay isn't implemented yet: {self._session_dir}")

    def grab(self) -> np.ndarray | None:
        raise NotImplementedError

    def stop(self) -> None:
        return None
