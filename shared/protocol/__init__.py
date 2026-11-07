"""The WebSocket contract between brain and overlay. See messages.py."""

from shared.protocol.messages import (
    PROTOCOL_VERSION,
    BrainMessage,
    BrainMessageAdapter,
    OverlayMessage,
    OverlayMessageAdapter,
    Protocol,
)

__all__ = [
    "PROTOCOL_VERSION",
    "BrainMessage",
    "BrainMessageAdapter",
    "OverlayMessage",
    "OverlayMessageAdapter",
    "Protocol",
]
