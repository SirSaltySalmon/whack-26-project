"""Recognises a player turn that only acknowledges, such as "okay", "thanks" or "sorry".

A teammate lets those be, and answering every one was much of why the partner talked so much:
live sessions had it reply to "Good.", "Sorry." and "Alright." with a sentence or two each. The
rules still answer one when the partner's last line asked something or the player's previous turn
hasn't been answered yet, because then the "okay" may be the answer or the cut-off turn's resume.
"""

import re

# Yes and no are left out on purpose: they answer questions, and a question asked a few lines
# back, such as memory's planned ones, is answered through the player's turn.
_PHRASES = (
    "thank you",
    "all right",
    "got it",
    "sounds good",
    "fair enough",
    "no worries",
    "never mind",
    "oh well",
)
_WORDS = frozenset(
    {"ok", "okay", "k", "alright", "right", "cool", "nice", "good", "great", "fine", "noted"}
    | {"thanks", "thx", "cheers", "sorry", "gotcha", "nevermind", "wow", "lol", "haha"}
    | {"oh", "ah", "hmm", "hm", "mm", "mhm", "uh", "um", "huh"}
)
# Longer than this, it's saying something even if every word is filler.
_MAX_WORDS = 4
_NOT_WORDS = re.compile(r"[^a-z' ]+")


def only_acknowledges(transcript: str) -> bool:
    """True for "Okay.", "Oh, thanks!" or "Alright, cool", but never for a question."""
    text = transcript.strip()
    if not text or text.endswith("?"):
        return False
    words = " ".join(_NOT_WORDS.sub(" ", text.lower()).split())
    for phrase in _PHRASES:
        words = words.replace(phrase, "ok")
    tokens = words.split()
    return 0 < len(tokens) <= _MAX_WORDS and all(token in _WORDS for token in tokens)
