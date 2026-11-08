"""The WebSocket contract between brain, overlay and Control Center.

See messages.py for the overlay's /ws messages and control.py for the Control Center's /control.
"""

from pydantic import BaseModel

from shared.protocol.control import (
    BrainDescription,
    ControlReply,
    ControlReplyAdapter,
    ControlRequest,
    ControlRequestAdapter,
)
from shared.protocol.messages import (
    PROTOCOL_VERSION,
    BrainMessage,
    BrainMessageAdapter,
    OverlayMessage,
    OverlayMessageAdapter,
)


class Protocol(BaseModel):
    """Exists only so one JSON Schema document can describe every direction."""

    brain: BrainMessage
    overlay: OverlayMessage
    control: ControlRequest
    control_reply: ControlReply
    description: BrainDescription


__all__ = [
    "PROTOCOL_VERSION",
    "BrainDescription",
    "BrainMessage",
    "BrainMessageAdapter",
    "ControlReply",
    "ControlReplyAdapter",
    "ControlRequest",
    "ControlRequestAdapter",
    "OverlayMessage",
    "OverlayMessageAdapter",
    "Protocol",
]
