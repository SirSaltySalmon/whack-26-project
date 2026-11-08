"""Turns parts of the brain off for one run, so testing one part doesn't spend another's quota.

Turning off a vendor drops its keys for this run only, so every part that needs it degrades the
way it already does without a key. The other parts are checked where they're built.
"""

import re

from brain.config import Settings

PARTS: dict[str, str] = {
    "anthropic": "every Claude call: by default the talker, vision and screen watching; deep "
    "thinking falls back to Gemini",
    "gemini": "every Gemini call: by default only the fallback for deep thinking",
    "observer": "Haiku watching the screen, and the progress guesses it wakes",
    "scout": "guessing the player's progress from their gear",
    "learner": "learning where the HUD is: readers still run from a saved or seeded profile",
    "voice": "the mic and speech: replies in subtitles, so add --type to talk",
    "tts": "speech only: it still listens, and replies in subtitles",
    "wiki": "finding the game's wiki, so no wiki or web lookups",
}

# Vendors are turned off by their keys, which every part already checks.
_KEYS: dict[str, tuple[str, ...]] = {
    "anthropic": ("anthropic_api_key",),
    "gemini": ("gemini_api_key",),
    "voice": ("deepgram_api_key", "elevenlabs_api_key"),
    "tts": ("elevenlabs_api_key",),
}


def parse_off(text: str) -> set[str]:
    """Reads `observer,tts` or `observer tts`. Raises ValueError naming any unknown part."""
    names = {name for name in re.split(r"[,\s]+", text.strip().lower()) if name}
    unknown = sorted(names - PARTS.keys())
    if unknown:
        raise ValueError(
            f"Unknown part to turn off: {', '.join(unknown)}. Choose from {', '.join(PARTS)}"
        )
    return names


def apply_off(settings: Settings, names: set[str] | None = None) -> Settings:
    """Merges `--off` with the DISABLE setting, and drops the keys of any vendor turned off."""
    off = parse_off(settings.disable) | (names or set())
    if not off:
        return settings
    update: dict[str, object] = {"disable": ",".join(sorted(off))}
    for name in off:
        update.update(dict.fromkeys(_KEYS.get(name, ()), None))
    return settings.model_copy(update=update)


def is_off(settings: Settings, name: str) -> bool:
    if name not in PARTS:
        # A typo here would silently leave a part running, so fail loudly instead.
        raise KeyError(f"No part called {name!r}")
    return name in parse_off(settings.disable)
