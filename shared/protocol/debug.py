"""Brain to overlay messages for the debug view, shown only with --debug-regions.

TypeScript types are generated from these models with the rest of the protocol.
"""

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


class DebugLatency(BaseModel):
    label: str  # Such as "frame → bark"
    ms: int = Field(ge=0)


class DebugBrain(BaseModel):
    """What the brain hears, decides and does right now, for a small panel over the game.

    Always the whole snapshot, about twice a second: the overlay hides the panel when they stop.
    """

    type: Literal["debug.brain"] = "debug.brain"
    # What speech recognition has so far while the player talks, then their last whole turn.
    hearing: str = ""
    hearing_live: bool = False
    mood: str | None = None  # Such as "positive" or "frustrated"
    mood_valence: float = Field(0.0, ge=-1.0, le=1.0)
    # The director's latest decision and why, such as "danger: quiet, cooling down".
    decision: str | None = None
    # A tool running or just run, such as "wiki: Life Crystal".
    doing: str | None = None
    focus: str | None = None  # How closely it's watching the screen: low, medium or high
    # The latest of each kind, newest first.
    latency: list[DebugLatency] = Field(default_factory=list)
