"""Splits a whole wiki page into short plain-text passages, each tagged with its section.

A lookup's card only has the intro and infobox, while recipes, drops and where to find something
sit further down the page. These passages let a lookup hand the model the part that answers the
player. Wiki HTML is untrusted, so only text comes out, never markup or links.
"""

from dataclasses import dataclass
from html.parser import HTMLParser

from brain.research.sanitize import _DROP_CLASSES, _DROP_TAGS, _VOID_TAGS, clean_text

# The outermost of these becomes one passage, with anything nested inside folded into it.
_BLOCKS = {"p", "li", "tr", "dt", "dd", "caption", "blockquote"}
_CELLS = {"td", "th"}
# Formatting inside running text, where a space would split words like "pre-<a>Hardmode</a>".
# Every other tag gets one, because wikis lay out "Lens" and its count "6" as separate spans.
_INLINE = {"a", "b", "i", "em", "strong", "small", "abbr", "code", "s", "u", "sub", "bdi"}
_HEADING_LEVELS = {"h2": 0, "h3": 1, "h4": 2}
# Standard MediaWiki markers for navigation and other text that isn't the article.
_NOT_ARTICLE = {"navigation-not-searchable", "noexcerpt", "catlinks", "printfooter"}
# Wrappers that don't make a heading inside them local to a box.
_PAGE_LEVEL = {"mw-parser-output", "mw-heading"}
MAX_PASSAGE_CHARS = 400
MAX_PASSAGES = 500


@dataclass
class _Node:
    tag: str
    classes: frozenset[str]
    drop: bool


def _drops(tag: str, classes: frozenset[str]) -> bool:
    return (
        tag in _DROP_TAGS
        or bool(classes & (_DROP_CLASSES | _NOT_ARTICLE))
        or any(c.endswith("navbox") for c in classes)
    )


class _PassageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.passages: list[str] = []
        self._stack: list[_Node] = []
        self._sections = ["", "", ""]
        # A heading inside a box, such as an infobox's "Drops", labels only that box's rows.
        self._local: list[tuple[int, str]] = []  # (depth of the box, label)
        self._heading: tuple[int | None, list[str]] | None = None  # (level, or None if local)
        self._heading_depth = 0
        self._block: list[str] | None = None
        self._block_tag = ""
        self._block_depth = 0
        self._row_has_data = False

    def _dropping(self) -> bool:
        return any(node.drop for node in self._stack)

    def _in_box(self) -> bool:
        return any(not (node.classes & _PAGE_LEVEL) for node in self._stack[:-1])

    def _text(self) -> list[str] | None:
        """Where text goes right now: an open heading, an open passage, or nowhere."""
        if self._dropping():
            return None
        return self._heading[1] if self._heading is not None else self._block

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID_TAGS:
            if tag == "br" and (text := self._text()) is not None:
                text.append(" ")
            return
        classes = frozenset((dict(attrs).get("class") or "").split())
        self._stack.append(_Node(tag, classes, _drops(tag, classes)))
        text = self._text()
        if text is not None:
            text.append(" | " if tag in _CELLS else "" if tag in _INLINE else " ")
            self._row_has_data = self._row_has_data or tag == "td"
            return
        if self._dropping():
            return
        in_box = self._in_box()
        if tag in _HEADING_LEVELS or ("title" in classes and in_box):
            level = None if in_box else _HEADING_LEVELS[tag]
            self._heading, self._heading_depth = (level, []), len(self._stack)
        elif tag in _BLOCKS:
            self._block, self._block_tag, self._block_depth = [], tag, len(self._stack)
            self._row_has_data = False

    def handle_endtag(self, tag: str) -> None:
        # Real-world HTML is often unbalanced, so pop to the nearest match and ignore strays.
        if not any(node.tag == tag for node in self._stack):
            return
        while self._stack:
            node = self._stack.pop()
            self._close()
            if node.tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if (text := self._text()) is not None:
            text.append(data)

    def _close(self) -> None:
        depth = len(self._stack)
        self._local = [(box, label) for box, label in self._local if box <= depth]
        if self._heading is not None and depth < self._heading_depth:
            self._end_heading()
        elif self._block is not None and depth < self._block_depth:
            self._emit()
            self._block = None

    def _end_heading(self) -> None:
        assert self._heading is not None
        level, parts = self._heading
        self._heading = None
        text = clean_text("".join(parts))
        if level is None:
            if text:
                self._local.append((len(self._stack), text))
            return
        self._sections[level] = text
        for deeper in range(level + 1, len(self._sections)):
            self._sections[deeper] = ""

    def _emit(self) -> None:
        if self._block_tag == "tr" and not self._row_has_data:
            return  # A header row, such as "Result | Ingredients", says nothing alone.
        text = clean_text("".join(self._block or []))
        text = " | ".join(cell.strip() for cell in text.split("|") if cell.strip())
        if len(text) < 2 or len(self.passages) >= MAX_PASSAGES:
            return
        labels = [name for name in self._sections if name]
        if self._local:
            # Only the innermost box label: an infobox's own title adds nothing to each row.
            labels.append(self._local[-1][1])
        passage = f"{', '.join(labels)}: {text}" if labels else text
        self.passages.append(passage[:MAX_PASSAGE_CHARS])


def page_passages(html: str) -> list[str]:
    """CPU-bound on a large page, so callers run it in a worker thread. Duplicates are dropped."""
    parser = _PassageParser()
    parser.feed(html)
    parser.close()
    return list(dict.fromkeys(parser.passages))
