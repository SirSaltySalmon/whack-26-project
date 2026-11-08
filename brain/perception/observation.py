"""What the assistant needs to know from one screenshot, in a form that works for any game.

Fields are ordered by how much they change what the assistant should do: is the player in a game at
all, are they in trouble, then what's going on and what's worth mentioning. A single frame can't
show what changed, so the brain should compare consecutive observations rather than ask the model.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from brain.perception.numbers import parse_fraction

OBSERVATION_PROMPT = """You are the eyes of an AI companion watching someone play a video game. \
It could be any game, so don't assume a genre. The companion uses your report to stay aware of \
what's happening, notice trouble, and know when something is worth mentioning.

Report only what is visible in this one frame. Never infer what happened before it or what the \
player intends. If something isn't clearly visible and readable, use null and add the field's name \
to "unsure". A wrong value is worse than null.

Use a specific name for an enemy, boss, item, character or place only when that name is written on \
screen. Otherwise describe it in plain words from how it looks, such as "a large eye-like boss" or \
"a sword", even if you think you recognize it. The image is small, so similar things are easy to \
mix up, and a wrong name misleads the companion far more than a plain description.

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
- health_percent: 0-100, how full it is. null if no health display is visible. For a row of \
icons such as hearts, count only bright, filled ones: a dark, hollow or faded icon is empty even \
when it keeps its outline and colour, and a shrunken one is partly empty.
- danger_level: how much trouble the player is in right now.
  none: nothing hostile is visible.
  low: a hostile is visible but not engaged, or an environmental hazard is nearby.
  medium: the player is fighting. Signs include projectiles, damage numbers, attack effects, or \
enemies labelled with health.
  high: a boss or a boss health bar, many enemies at once, or fighting with low health.
- threats: visible enemies or hazards, by their on-screen names when written, else in plain \
words. Only list what's clearly hostile or harmful. Friendly or idle characters, ambient wildlife, \
weather and speech bubbles aren't threats. Empty if none.
- selected_item: the held or selected item's name, only if it's written on screen. Otherwise null.
- menu_title: the heading of the open menu or panel, only if written. Not the game's logo.
- location: the visible environment in a few plain words, or null.
- on_screen_text: up to 3 short pieces of text that matter most, such as objectives, warnings or \
prompts. Not menu lists or FPS counters.
- notable: the one thing the companion should know about this frame in at most 12 words, such as \
low health, a boss, an objective or a prompt. null if nothing stands out.
- unsure: names of the fields you were unsure about."""

# Added only for the debug view, because every box costs output tokens on a call that runs about
# once a second. Pixel boxes, because Claude places those well and 0-1000 boxes badly.
SIGHTINGS_PROMPT = """
- sightings: up to 4 things in the game world worth a look, such as the enemies, threats, items or \
characters your report mentions. Never the fixed HUD: health, mana, hotbar, minimap, buttons. Each \
has a label of at most 4 words and box_px: [x_min, y_min, x_max, y_max], tight around it, in \
pixels of this {width} x {height} image. Empty if nothing stands out."""


def sightings_prompt(width: int, height: int) -> str:
    return OBSERVATION_PROMPT + SIGHTINGS_PROMPT.format(width=width, height=height)


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
        numbers = parse_fraction(self.health_raw or "")
        if numbers:
            return numbers[0] / numbers[1]
        return None if self.health_percent is None else self.health_percent / 100


class Sighting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    box_px: list[float]


class SightedObservation(Observation):
    """An observation that also says where things are, asked for only while debugging."""

    # Required, so structured output always fills it in rather than skipping it.
    sightings: list[Sighting]

    @field_validator("sightings", mode="before")
    @classmethod
    def _drop_malformed(cls, value: object) -> object:
        # One bad box must not cost the whole report, which drives danger and events.
        if not isinstance(value, list):
            return []
        kept = []
        for item in value:
            try:
                kept.append(Sighting.model_validate(item))
            except ValueError:
                continue
        return kept
