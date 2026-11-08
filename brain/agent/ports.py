"""What the player-turn tools need from the rest of the brain, kept apart from handlers.py, which
is near the file length limit."""

from dataclasses import dataclass
from typing import Protocol

from brain.agent.memory_tools import PlayerMemory
from shared.protocol import BrainMessage
from shared.protocol.messages import Settings


class Overlay(Protocol):
    @property
    def display_scale(self) -> float: ...

    # The player's settings, for whether they've turned the partner's vision off.
    @property
    def settings(self) -> Settings: ...

    async def send(self, message: BrainMessage) -> None: ...


class AgentMemory(PlayerMemory, Protocol):
    async def wonder(self, subject: str, attribute: str, text: str) -> object | None: ...


@dataclass(frozen=True)
class AgentLimits:
    mask_padding_px: int
    closeup_max_edge_px: int
    max_frame_age_s: float
    pointer_ttl_ms: int
    # --debug-regions: draw what look_closer, point_at and look_back used over the game.
    show_sightings: bool = False
