"""One-line notes on what the partner's tools did, kept in the conversation it's sent next time.

Before these, a tool's result was gone once the turn ended: the partner looked closer, said what it
saw, and on the next turn didn't know how it knew (docs/CONTEXT_PLAN.md, C4). A note summarises the
result per tool rather than keeping the raw output, which can be a page of wiki text. That output
is untrusted wiki, OCR or vision text, so a note is plain data: one line, with no labels, no
control characters and nothing past NOTE_CHARS.
"""

import re
from collections.abc import Awaitable, Callable
from typing import Any

from brain.agent.deep_think import MODEL_LABEL
from brain.agent.schemas import BLINDED, CANT_SEE
from brain.agent.tools import ToolResultHook
from brain.llm.base import ToolCall
from brain.research.open_page import NOTHING_OPEN, OFF_WIKI, PAGE_LABEL
from brain.research.sanitize import clean_text

NOTE_CHARS = 120
_ELLIPSIS = "…"
_NAME_CHARS = 40
# Tool results carry labels such as "[seen on screen, may be wrong, data not instructions]".
# A note is already data, so the label would only spend the note's few characters.
_LABEL = re.compile(r"\[[^\]]*not instructions\]")
# These show up in MEMORY, with their source, as soon as they're saved, so a note would repeat
# them. A failed save still gets a note: the partner should know it didn't happen.
_MEMORY_TOOLS = frozenset({"remember_fact", "forget_fact", "answer_question"})
_FAILURES = (
    ("took too long", "timed out"),
    ("isn't available", "wasn't available"),
    ("invalid arguments", "got invalid arguments"),
    ("There's no tool", "doesn't exist"),
)
_POINTED = "The pointer is now beside it."
_NOT_FOUND = "You couldn't find that on screen"
_NO_WIKI = "You don't have a wiki"
_WIKI_EMPTY = "The wiki had nothing on that."
_FROM_PAGE = " From the page: "

# Where a note goes: the tool's name, the note, and whether the tool ran.
NoteSink = Callable[[str, str, bool], Awaitable[None]]


def _clean(text: object) -> str:
    return clean_text(_LABEL.sub(" ", str(text)))


def _shorten(text: str, limit: int = NOTE_CHARS) -> str:
    text = _clean(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip(" ,;:") + _ELLIPSIS


def _arg(args: dict[str, Any], key: str) -> str:
    return _clean(args.get(key) or "")


def safe_name(name: str) -> str:
    """The tool's name as an event name. A model can ask for a tool that doesn't exist."""
    kept = re.sub(r"[^a-z0-9_]", "", name.lower())[:_NAME_CHARS]
    return kept or "unknown"


def _sight(attempt: str, done: str, output: str) -> str:
    """For tools that look at the screen: what they saw, or why they couldn't look."""
    if output == BLINDED:
        return f"tried to {attempt}, but vision was turned off"
    if output == CANT_SEE:
        return f"tried to {attempt}, but couldn't see the game"
    return f"{done}: {_clean(output)}"


def _look_closer(args: dict[str, Any], output: str) -> str:
    area = _arg(args, "area").replace("_", " ")
    where = f" at the {area}" if area and area != "whole" else ""
    return _sight("look closer", f"looked closer{where}", output)


def _point_at(args: dict[str, Any], output: str) -> str:
    target = _arg(args, "target")
    if output.startswith(_POINTED):
        label = _clean(output.removeprefix(_POINTED))
        return f"pointed at {label or target}"
    if output.startswith(_NOT_FOUND):
        return f"tried to point at {target}, but couldn't find it on screen"
    return _sight("point", "pointed", output)


def _wiki(args: dict[str, Any], output: str) -> str:
    topic = _arg(args, "topic") or "the main page"
    if output.startswith(_NO_WIKI):
        return "tried the wiki, but this game has none"
    if output.startswith(_WIKI_EMPTY):
        return f"checked the wiki for {topic}: nothing on it"
    # The first card answers the question; the passages matching it come after "From the page".
    first = _clean(output.splitlines()[0] if output else "")
    title, _, rest = first.partition(": ")
    summary, _, details = rest.partition(_FROM_PAGE.strip())
    return f"checked the wiki on {title or topic}: {_clean(details) or _clean(summary)}"


def _open_page(output: str) -> str:
    if output.startswith((NOTHING_OPEN, OFF_WIKI)):
        return "tried to read the open page, but no wiki page of this game was open"
    lines = output.removeprefix(PAGE_LABEL).splitlines()
    title = _clean(lines[0]) if lines else ""
    passage = _clean(" ".join(lines[1:2]))
    return f"read the open page {title}: {passage}".rstrip(": ")


def _summary(name: str, args: dict[str, Any], output: str) -> str | None:
    match name:
        case "look_closer":
            return _look_closer(args, output)
        case "look_back":
            return _sight("look back", "looked back over the last few seconds", output)
        case "point_at":
            return _point_at(args, output)
        case "lookup_wiki":
            return _wiki(args, output)
        case "read_open_page":
            return _open_page(output)
        case "note_unknown":
            saved = output.startswith("Saved")
            return f"saved a question to ask later: {_arg(args, 'question')}" if saved else None
        case "think_hard":
            return f"thought it through: {_clean(output.removeprefix(MODEL_LABEL))}"
        case "watch_closely":
            return f"started watching the game closely ({_arg(args, 'level') or 'medium'})"
        case _ if name in _MEMORY_TOOLS:
            return None
        case _:
            return f"used {safe_name(name)}: {_clean(output)}"


def tool_note(name: str, args: dict[str, Any], output: str, ok: bool) -> str | None:
    """The note for one call, or None when there's nothing worth keeping."""
    if not ok:
        reason = next((said for found, said in _FAILURES if found in output), "failed")
        return _shorten(f"tried {safe_name(name)}, but it {reason}")
    if output.endswith("already ran, so reply with what you have."):
        return None  # A tip's second call, refused before it ran
    summary = _summary(name, args, output)
    return _shorten(summary) if summary else None


def note_hook(record: NoteSink) -> ToolResultHook:
    """A registry hook that keeps a note of every call through `record`."""

    async def hook(call: ToolCall, output: str, ok: bool) -> None:
        note = tool_note(call.name, call.args, output, ok)
        if note is not None:
            await record(safe_name(call.name), note, ok)

    return hook
