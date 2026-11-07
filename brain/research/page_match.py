"""Picks the passages of an open wiki page that bear on what the player said. Pure, with no model.

Matching is by shared words, so it's instant and runs on the voice path. It only has to be good
enough to hand the talker the right paragraph; the read_open_page tool covers the misses.
"""

import re
from collections.abc import Sequence

from brain.memory.fts import query_terms

# Terms this long also match longer words, so "summon" finds "summoning".
PREFIX_MIN_LETTERS = 4
# Words that mean "the page itself", for "what does this say?". English only, like the stopwords.
_PAGE_WORDS = frozenset({"page", "article", "wiki", "here", "this", "says"})
_WORD = re.compile(r"\w+", re.UNICODE)


def _term_pattern(term: str) -> re.Pattern[str]:
    tail = r"\w*" if len(term) >= PREFIX_MIN_LETTERS else ""
    return re.compile(rf"\b{re.escape(term)}{tail}\b", re.IGNORECASE | re.UNICODE)


def refers_to_page(transcript: str) -> bool:
    return any(word.lower() in _PAGE_WORDS for word in _WORD.findall(transcript))


def fit(passages: Sequence[str], max_chars: int) -> list[str]:
    """Takes passages in order until the next one wouldn't fit, counting a newline between each.

    A first passage longer than the cap is cut rather than dropped, so a page written as one
    long paragraph still yields something.
    """
    taken: list[str] = []
    used = 0
    for passage in passages:
        cost = len(passage) + (1 if taken else 0)
        if used + cost > max_chars:
            if not taken and max_chars > 0:
                taken.append(passage[:max_chars])
            break
        taken.append(passage)
        used += cost
    return taken


def match_passages(
    transcript: str, passages: Sequence[str], visible: Sequence[str], max_chars: int
) -> list[str]:
    """Best-scoring passages up to max_chars, in page order. Empty means send nothing.

    A passage scores one point per distinct term it contains. Ties go to passages in view, since
    that's probably what the player is reading. With no match at all, a transcript that refers to
    the page gets the part in view instead.
    """
    patterns = [_term_pattern(term) for term in query_terms(transcript)]
    in_view = set(visible)
    scored = [
        (score, index, passage)
        for index, passage in enumerate(passages)
        if (score := sum(1 for pattern in patterns if pattern.search(passage))) > 0
    ]
    if not scored:
        return fit(visible, max_chars) if refers_to_page(transcript) else []

    scored.sort(key=lambda item: (-item[0], item[2] not in in_view, item[1]))
    chosen: list[tuple[int, str]] = []
    used = 0
    for _score, index, passage in scored:
        cost = len(passage) + (1 if chosen else 0)
        if used + cost > max_chars:
            if not chosen and max_chars > 0:
                chosen.append((index, passage[:max_chars]))
                break
            # A shorter, lower-scoring passage may still fit.
            continue
        chosen.append((index, passage))
        used += cost
    return [passage for _index, passage in sorted(chosen)]
