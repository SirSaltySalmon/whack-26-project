"""Pre-generated lines, so a reaction can skip the model and TTS.

The bank that generates and caches them is still to come: see WP6 in docs/REMAINING_WORK.md.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Bark:
    text: str
    pcm: bytes  # 16-bit mono
    sample_rate: int
