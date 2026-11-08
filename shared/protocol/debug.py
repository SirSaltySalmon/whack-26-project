"""The debug view drawn over the game with --debug-regions. Coordinates are Electron DIPs."""

from typing import Literal

from pydantic import BaseModel, Field

from shared.protocol.geometry import Rect


class DebugRegion(BaseModel):
    name: str
    # Overlay window coordinates, like PointerFly.target.
    rect: Rect
    status: Literal["ok", "masked", "unreadable"]
    # What the reader read, such as "72/100" or "62%".
    display: str | None = None


class DebugRegions(BaseModel):
    """A debug view of where each HUD region was found and what its reader reads.

    Always the full current set, so an empty list clears the view. Send it about twice a second
    while debugging: the overlay hides the view when messages stop.
    """

    type: Literal["debug.regions"] = "debug.regions"
    regions: list[DebugRegion]


class DebugSighting(BaseModel):
    """Something a model looked at or noticed, drawn over the game while debugging."""

    label: str
    # Overlay window coordinates, like DebugRegion.rect.
    rect: Rect
    # noticed: the observer's report. look, point and look_back: what a player-turn tool used.
    kind: Literal["noticed", "look", "point", "look_back"]
    ttl_ms: int = Field(gt=0)


class DebugSightings(BaseModel):
    """Adds sightings to the debug view. Each fades on its own once its ttl_ms runs out.

    Sent only with --debug-regions, so the overlay draws whatever arrives.
    """

    type: Literal["debug.sightings"] = "debug.sightings"
    sightings: list[DebugSighting]
