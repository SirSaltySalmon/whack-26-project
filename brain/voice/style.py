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


def style_values(style: str | None) -> dict[str, float]:
    """The voice settings for a style. Anything unknown gets the default style."""
    if style in VOICE_STYLES:
        return VOICE_STYLES[style]  # type: ignore[index]  # Checked just above.
    return VOICE_STYLES[DEFAULT_STYLE]
