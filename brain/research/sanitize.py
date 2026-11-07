"""Turns untrusted wiki HTML into short plain text for cards.

Wiki HTML is data, never instructions. Nothing here keeps markup, links or scripts: the overlay
only ever receives plain text and an http(s) image URL. Uses the stdlib parser so it works on any
MediaWiki skin without extra dependencies.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

# Never contain readable article text, so their whole subtree is dropped.
_DROP_TAGS = {"script", "style", "noscript", "template", "svg", "math", "sup"}
_DROP_CLASSES = {
    "mw-editsection",
    "reference",
    "references",
    "mw-references-wrap",
    "navbox",
    "toc",
    "noprint",
    "mw-empty-elt",
    "error",
}
_VOID_TAGS = {"img", "br", "hr", "meta", "link", "input", "wbr", "source", "col", "area", "base"}
# A <p> nested inside one of these is a message box, caption or table, not the article intro.
_BLOCK_CONTAINERS = {"div", "table", "aside", "figure", "ul", "ol", "dl", "blockquote", "section"}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


@dataclass
class ParsedArticle:
    paragraphs: list[str] = field(default_factory=list)
    infobox: list[tuple[str, str]] = field(default_factory=list)
    image_url: str | None = None


@dataclass
class _Node:
    tag: str
    classes: set[str]
    drop: bool
    infobox: bool


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.result = ParsedArticle()
        self._stack: list[_Node] = []
        self._seen_heading = False
        self._infobox_done = False
        self._para: list[str] | None = None
        self._label: list[str] | None = None
        self._value: list[str] | None = None

    # --- Stack state -------------------------------------------------------------------------
    def _dropping(self) -> bool:
        return any(n.drop for n in self._stack)

    def _in_infobox(self) -> bool:
        return any(n.infobox for n in self._stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = set((attr.get("class") or "").split())
        if tag in _VOID_TAGS:
            self._void(tag, attr)
            return
        is_infobox = (
            not self._infobox_done
            and not self._in_infobox()
            and any(c == "infobox" or c == "portable-infobox" for c in classes)
        )
        drop = tag in _DROP_TAGS or bool(classes & _DROP_CLASSES)
        self._stack.append(_Node(tag, classes, drop, is_infobox))
        if self._dropping():
            return
        if self._in_infobox():
            self._infobox_start(tag, classes)
        elif tag in _HEADINGS or "mw-heading" in classes:
            # Only article headings end the intro; infoboxes have their own title headings.
            self._seen_heading = True
        elif tag == "p" and not self._seen_heading and self._is_top_level_paragraph():
            self._para = []

    def handle_endtag(self, tag: str) -> None:
        # Real-world HTML is often unbalanced, so pop to the nearest match and ignore strays.
        if not any(n.tag == tag for n in self._stack):
            return
        while self._stack:
            node = self._stack.pop()
            self._close(node)
            if node.tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._dropping():
            return
        # Value before label: a label buffer stays open while its value cell is being read.
        for buf in (self._value, self._label, self._para):
            if buf is not None:
                buf.append(data)
                return

    def _void(self, tag: str, attr: dict[str, str | None]) -> None:
        if self._dropping():
            return
        if tag == "br":
            self.handle_data(" ")
        elif tag == "img" and self._in_infobox():
            src = attr.get("src") or ""
            if self.result.image_url is None and src:
                self.result.image_url = src
            # Icon-only cells (for example immunities) carry their meaning in alt text.
            if self._value is not None and attr.get("alt"):
                self._value.append(f" {attr['alt']} ")

    def _is_top_level_paragraph(self) -> bool:
        parents = self._stack[:-1]
        return not any(
            n.tag in _BLOCK_CONTAINERS and "mw-parser-output" not in n.classes for n in parents
        )

    # --- Infobox rows: <th>/<td> tables and Fandom portable infoboxes ------------------------
    def _infobox_start(self, tag: str, classes: set[str]) -> None:
        if tag == "th" or "pi-data-label" in classes:
            self._label = []
        elif (tag == "td" or "pi-data-value" in classes) and self._label is not None:
            self._value = []
        elif self._value is not None:
            # Separate inline pieces so "Surface + Night" and "Space" don't run together.
            self._value.append(" ")

    def _close(self, node: _Node) -> None:
        if node.tag == "p" and self._para is not None and not self._in_infobox():
            text = clean_text("".join(self._para))
            if text:
                self.result.paragraphs.append(text)
            self._para = None
        if self._value is not None and (node.tag == "td" or "pi-data-value" in node.classes):
            label = clean_text("".join(self._label or []))
            value = clean_text("".join(self._value))
            if label and value:
                self.result.infobox.append((label, value))
            self._label = self._value = None
        elif self._label is not None and node.tag == "tr":
            self._label = None  # Header-only row, such as a section title.
        if node.infobox:
            self._infobox_done = True
            self._label = self._value = None


def clean_text(text: str) -> str:
    """Drops control and invisible format characters (bidi overrides, zero-width) and collapses
    whitespace, so hidden text can't reach the overlay or a model."""
    kept = "".join(
        " " if ch in "\t\n\r" else ch
        for ch in text
        if ch in "\t\n\r" or unicodedata.category(ch) not in {"Cc", "Cf", "Co", "Cs"}
    )
    kept = re.sub(r"\s+", " ", kept).strip()
    return re.sub(r" ([,.;:!?)])", r"\1", kept).replace("( ", "(")


def parse_article(html: str, base_url: str) -> ParsedArticle:
    parser = _ArticleParser()
    parser.feed(html)
    parser.close()
    result = parser.result
    result.image_url = safe_http_url(result.image_url, base_url)
    return result


def safe_http_url(url: str | None, base_url: str) -> str | None:
    if not url:
        return None
    absolute = urljoin(base_url, url)
    return absolute if urlparse(absolute).scheme in {"http", "https"} else None


def truncate_sentences(text: str, max_sentences: int, max_chars: int) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out = " ".join(sentences[:max_sentences])
    if len(out) <= max_chars:
        return out
    cut = out[: max_chars - 1].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"
