"""What the assistant needs to know from one screenshot, in a form that works for any game.

Fields are ordered by how much they change what the assistant should do: is the player in a game at
all, are they in trouble, then what's going on and what's worth mentioning. A single frame can't
show what changed, so the brain should compare consecutive observations rather than ask the model.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

_HEALTH_NUMBERS = re.compile(r"(\d[\d,]*)\s*/\s*(\d[\d,]*)")

OBSERVATION_PROMPT = """You are the eyes of an AI companion watching someone play a video game. \
It could be any game, so don't assume a genre. The companion uses your report to stay aware of \
what's happening, notice trouble, and know when something is worth mentioning.

Report only what is visible in this one frame. Never infer what happened before it or what the \
player intends. If something isn't clearly visible and readable, use null and add the field's name \
to "unsure". A wrong value is worse than null.

Fields:
- screen_type: gameplay (the game world, with no large panel covering it), menu (title screen, \
options, lists of saves or worlds, credits, pause or settings panels, even over a game world), \
dialogue (a conversation box is open), inventory (an item grid or equipment panel is open), map, \
loading, cutscene, death (a game over or respawn screen), other.
- summary: at most 15 words on what is happening right now.
- player_action: what the player is clearly doing, or null if one frame can't show it.
- health_visible: whether the player's own health display is on screen. Coins, scores, ammo and \
enemy health aren't player health.
- health_raw: exactly what that display shows, such as "72/100" or "5 hearts". Copy any numbers.
- health_percent: 0-100, how full it is. null if no health display is visible.
- danger_level: how much trouble the player is in right now.
  none: nothing hostile is visible.
  low: a hostile is visible but not engaged, or an environmental hazard is nearby.
  medium: the player is fighting. Signs include projectiles, damage numbers, attack effects, or \
enemies labelled with health.
  high: a boss or a boss health bar, many enemies at once, or fighting with low health.
- threats: visible enemies or hazards, using their on-screen names when written. Only list what's \
clearly hostile or harmful. Friendly or idle characters, ambient wildlife, weather and speech \
bubbles aren't threats. Empty if none.
- selected_item: the held or selected item's name, only if it's written on screen.
- menu_title: the heading of the open menu or panel, only if written. Not the game's logo.
- location: the visible environment in a few plain words, or null.
- on_screen_text: up to 3 short pieces of text that matter most, such as objectives, warnings or \
prompts. Not menu lists or FPS counters.
- notable: the one thing the companion should know about this frame in at most 12 words, such as \
low health, a boss, an objective or a prompt. null if nothing stands out.
- unsure: names of the fields you were unsure about."""


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    screen_type: Literal[
        "gameplay", "menu", "dialogue", "inventory", "map", "loading", "cutscene", "death", "other"
    ]
    summary: str
    player_action: str | None
    health_visible: bool
    health_raw: str | None
    health_percent: int | None
    danger_level: Literal["none", "low", "medium", "high"]
    threats: list[str]
    selected_item: str | None
    menu_title: str | None
    location: str | None
    on_screen_text: list[str]
    notable: str | None
    unsure: list[str]

    @property
    def health_fraction(self) -> float | None:
        """Prefers numbers read off the screen: the model reads them well but does the sum badly."""
        if not self.health_visible:
            return None
        match = _HEALTH_NUMBERS.search(self.health_raw or "")
        if match:
            current = int(match.group(1).replace(",", ""))
            maximum = int(match.group(2).replace(",", ""))
            if maximum > 0 and current <= maximum:
                return current / maximum
        return None if self.health_percent is None else self.health_percent / 100
