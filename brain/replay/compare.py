"""Compares the messages two runs sent, so a replay can be checked against an earlier one.

Timing, IDs and geometry change from run to run without the behaviour changing, so they're
dropped. What's left is each message's type and content, in order.
"""

import argparse
import difflib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from brain.replay.format import MESSAGES, MessageRecord, read_jsonl

MATCH = 0
DIFFERENT = 1
USAGE_ERROR = 2

# Geometry depends on window positions and display scale, and lifetimes may be tuned, so neither
# says anything about whether the partner behaved the same.
_IGNORED_KEYS = frozenset({"id", "ttl_ms", "target", "rect", "rects", "x", "y", "width", "height"})


def load_messages(path: Path) -> list[dict[str, Any]]:
    """Every message in a messages.jsonl file. Unreadable lines, such as a last line cut short by
    a crash, are skipped with a warning."""
    return [record.message for record in read_jsonl(path, MessageRecord)]


def normalize(message: dict[str, Any]) -> dict[str, Any]:
    """The message without its IDs, lifetimes and geometry, at any depth."""
    return {key: _normalize_value(value) for key, value in message.items() if _kept(key)}


def _kept(key: str) -> bool:
    return key not in _IGNORED_KEYS and not key.endswith("_id")


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return normalize(value)
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    return value


def summarize(message: dict[str, Any]) -> str:
    """One line that's the same for equivalent messages: the type, then the content as JSON."""
    content = normalize(message)
    kind = content.pop("type", "<no type>")
    return f"{kind} {json.dumps(content, sort_keys=True)}"


def compare(
    a: Sequence[dict[str, Any]],
    b: Sequence[dict[str, Any]],
    *,
    a_name: str = "a",
    b_name: str = "b",
) -> list[str]:
    """Unified diff lines between the two runs' messages, or [] when they match."""
    return list(
        difflib.unified_diff(
            [summarize(message) for message in a],
            [summarize(message) for message in b],
            fromfile=a_name,
            tofile=b_name,
            lineterm="",
        )
    )


def _messages_file(path: Path) -> Path:
    """Accepts a session directory as well as its messages file."""
    return path / MESSAGES if path.is_dir() else path


def main(argv: Sequence[str]) -> int:
    """Exits 0 when the runs match, 1 when they differ and 2 on a usage error or missing file."""
    parser = argparse.ArgumentParser(
        prog="compare_replay",
        description="Compare two runs' messages.jsonl, ignoring timing, IDs and rectangles.",
    )
    parser.add_argument("a", type=Path, help="messages.jsonl, or the session directory holding it")
    parser.add_argument("b", type=Path, help="messages.jsonl, or the session directory holding it")
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as stop:
        # argparse exits 0 for --help and 2 for bad arguments; return rather than exit, for tests.
        return MATCH if stop.code == 0 else USAGE_ERROR

    paths = [_messages_file(args.a), _messages_file(args.b)]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        # read_jsonl treats a missing file as empty, which would hide a typo as a difference.
        for path in missing:
            print(f"compare_replay: no such file: {path}", file=sys.stderr)
        return USAGE_ERROR

    a, b = load_messages(paths[0]), load_messages(paths[1])
    diff = compare(a, b, a_name=str(paths[0]), b_name=str(paths[1]))
    if not diff:
        print(f"Match: {len(a)} messages.")
        return MATCH
    for line in diff:
        print(line)
    print(f"Different: {len(a)} messages in {paths[0]}, {len(b)} in {paths[1]}.")
    return DIFFERENT
