"""How much the ElevenLabs voice varies its delivery, chosen in settings.

Values are explicit for both styles, never left unset: Pipecat only sends the fields it's given,
so switching back from "expressive" with unset fields would keep the expressive values.
"""

from typing import Literal

VoiceStyle = Literal["expressive", "classic"]

# Lower stability lets pitch and pace move with the words; below about 0.25 the voice can wobble.
# Style exaggerates the voice's own character, at a small cost in latency.
VOICE_STYLES: dict[VoiceStyle, dict[str, float]] = {
    "expressive": {"stability": 0.3, "style": 0.5, "speed": 1.05},
    # ElevenLabs' own defaults, which is what the voice used before styles existed.
    "classic": {"stability": 0.5, "style": 0.0, "speed": 1.0},
}

DEFAULT_STYLE: VoiceStyle = "expressive"

# In danger, lines come a little faster. ElevenLabs accepts up to 1.2, and words start to blur
# near it, so this stays a nudge.
URGENT_SPEED_UP = 0.1
MAX_SPEED = 1.2


def style_values(style: str | None, urgent: bool = False) -> dict[str, float]:
    """The voice settings for a style. Anything unknown gets the default style."""
    key: VoiceStyle = style if style in VOICE_STYLES else DEFAULT_STYLE  # type: ignore[assignment]
    values = dict(VOICE_STYLES[key])
    if urgent:
        values["speed"] = min(MAX_SPEED, values["speed"] + URGENT_SPEED_UP)
    return values
