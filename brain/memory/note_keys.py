"""Keeps a session note's drafted facts from sitting beside what memory already holds.

The note reads the same conversation the talker's tools already wrote from, and it names keys its
own way: `player / preferred playstyle` beside `player / playstyle`, or `player / game mode` beside
a planned question's `playthrough / game mode`. Exact keys can't catch that, so these compare keys
by their words. Pure, so the rules are tested without a database.
"""

from collections.abc import Iterable
from typing import NamedTuple

# Both mean the person playing and their run, and models swap them freely for the same thing.
SELF_SUBJECTS = frozenset({"player", "playthrough"})


class Key(NamedTuple):
    subject: str
    attribute: str


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def _words(text: str) -> frozenset[str]:
    return frozenset(_norm(text).split())


def _same_subject(left: str, right: str) -> bool:
    a, b = _norm(left), _norm(right)
    return a == b or (a in SELF_SUBJECTS and b in SELF_SUBJECTS)


def is_exact(left: Key, right: Key) -> bool:
    return _norm(left.subject) == _norm(right.subject) and _norm(left.attribute) == _norm(
        right.attribute
    )


def names_same(left: Key, right: Key) -> bool:
    """Same attribute, about the same thing, such as `player / game mode` and
    `playthrough / game mode`."""
    return _same_subject(left.subject, right.subject) and _norm(left.attribute) == _norm(
        right.attribute
    )


def restates(drafted: Key, recorded: Key) -> bool:
    """A different key for what `recorded` already says: one attribute's words hold the other's,
    such as `preferred playstyle` and `playstyle`. The exact key isn't a restatement: the note
    prompt keeps exact keys for corrections, and memory's trust rules settle those."""
    if is_exact(drafted, recorded) or not _same_subject(drafted.subject, recorded.subject):
        return False
    left, right = _words(drafted.attribute), _words(recorded.attribute)
    return bool(left and right) and (left <= right or right <= left)


def existing_key(drafted: Key, known: Iterable[Key]) -> Key:
    """The one known key that names the same thing, so the fact lands on it. The drafted key when
    it's already known exactly, or when none or several match, since guessing between several
    could close the wrong fact."""
    matches: dict[Key, Key] = {}
    for key in known:
        if is_exact(drafted, key):
            return drafted
        if names_same(drafted, key):
            matches.setdefault(Key(_norm(key.subject), _norm(key.attribute)), key)
    return next(iter(matches.values())) if len(matches) == 1 else drafted
