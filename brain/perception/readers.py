"""Compiled readers: cheap local checks built from regions the vision model learned.

TODO(track 2): implement OCR, colour and scene-hash readers, then publish GameEvents on the bus.
Readers run off the event loop and must never call a vision model.
"""

from typing import Protocol

import numpy as np

from brain.events import GameEvent


class Reader(Protocol):
    def read(self, image: np.ndarray) -> list[GameEvent]:
        """`image` must already be masked with mask_overlay."""
        ...
