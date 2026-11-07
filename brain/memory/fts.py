"""Turns free text into a safe FTS5 query."""

import re

_TOKEN = re.compile(r"\w+", re.UNICODE)
# Without this, a question like "what is it" matches almost every note. Filler in other languages
# only costs some ranking quality, so a short English list is enough.
_STOPWORDS = frozenset(
    "a an and are at be can did do does for how i in is it me my of on or should so that the their"
    " there they this to was we what when where which who why will with you your".split()
)


def query_terms(text: str) -> list[str]:
    """The distinct lowercase words worth searching for, in order, with stopwords dropped."""
    tokens = [token.lower() for token in _TOKEN.findall(text)]
    return list(dict.fromkeys(token for token in tokens if token not in _STOPWORDS))


def to_match_query(text: str) -> str | None:
    """Returns an FTS5 MATCH string, or None when the text has nothing worth searching for.

    Transcripts and OCR contain apostrophes, hyphens and question marks, which are FTS5 syntax
    and raise errors when passed through raw. Quoting every token makes them literals, which also
    stops operators like NEAR or OR in player speech from being interpreted.
    """
    terms = query_terms(text)
    if not terms:
        return None
    return " OR ".join(f'"{term}"' for term in terms)
