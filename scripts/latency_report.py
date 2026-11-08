"""Summarises the latency and event-loop lines of saved brain logs as a Markdown table.

Usage: python scripts/latency_report.py run.log [more.log ...]
With no files, or `-`, it reads stdin. Save a live run's log with
    python -m brain --live --record 2>&1 | Tee-Object run.log
Exits 0 after printing the report, 1 when no line matched and 2 when a file can't be read.

Frame-to-voice times are split by source (`reader` or `observer`), with their noticed and spoke
parts as rows of their own, so the slow half is visible. Event-to-bark times also get a row per
event, so one slow bark stands out. Percentiles are nearest-rank: the value at position
ceil(p / 100 * count) in sorted order, so every figure is a time that really happened.
"""

import argparse
import codecs
import math
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brain.loop_watch import WARN_MS  # noqa: E402

FOUND = 0
NOTHING_MATCHED = 1
UNREADABLE = 2

# Matched anywhere in the log: the quiet and --verbose formats put different prefixes first, and
# Windows PowerShell 5 wraps long lines at the console width, so any space may be a line break.
_NUMBER = r"(-?\d+(?:\.\d+)?)"


def _phrase(text: str) -> str:
    return r"\s+".join(re.escape(word) for word in text.split())


def _ms(prefix: str) -> str:
    return rf"{_phrase(prefix)}\s+{_NUMBER}\s+ms\b"


SIMPLE_KINDS = {
    "player turn": re.compile(_ms("Latency: player turn took")),
    "end of turn to first audio": re.compile(_ms("Latency: end of turn to first audio")),
}
EVENT_TO_BARK = re.compile(_ms("Latency: event to bark") + r"(?:\s+\(([\w.-]+)\))?")
FRAME_TO = re.compile(
    rf"{_phrase('Latency: frame to')}\s+(bark|first\s+audio)\s+{_NUMBER}\s+ms\s+"
    rf"\([^()]*?\s+from\s+(\w+):\s+noticed\s+in\s+{_NUMBER},\s+spoke\s+in\s+{_NUMBER}\)"
)
STALLED = re.compile(_ms("Event loop stalled"))
LONGEST = re.compile(_ms("Event loop: longest stall") + rf"\s+over\s+{_NUMBER}\s+s\b")

KIND_ORDER = (
    "player turn",
    "event to bark",
    "end of turn to first audio",
    "frame to bark",
    "frame to first audio",
)
PARTS = ("", "noticed", "spoke")


@dataclass(frozen=True)
class Kind:
    """One row of the table: a latency kind, what it's split by if anything (a frame time's
    source, a bark's event), and which part."""

    name: str
    source: str = ""
    part: str = ""

    def label(self) -> str:
        label = f"{self.name} ({self.source})" if self.source else self.name
        return f"{label}: {self.part}" if self.part else label

    def sort_key(self) -> tuple[int, str, int]:
        return KIND_ORDER.index(self.name), self.source, PARTS.index(self.part)


@dataclass
class Samples:
    latency: dict[Kind, list[float]] = field(default_factory=dict)
    stalls: list[float] = field(default_factory=list)
    longest: list[float] = field(default_factory=list)
    watched_s: list[float] = field(default_factory=list)

    def add(self, kind: Kind, ms: str) -> None:
        self.latency.setdefault(kind, []).append(float(ms))

    def empty(self) -> bool:
        return not (self.latency or self.stalls or self.longest)


def decode_log(data: bytes) -> str:
    """Windows PowerShell 5's Tee-Object writes UTF-16 with a BOM; PowerShell 7 writes UTF-8."""
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


def parse_lines(lines: Iterable[str], samples: Samples | None = None) -> Samples:
    """Adds every recognised measurement to samples, ignoring the rest of the log."""
    return parse_text("\n".join(lines), samples)


def parse_text(text: str, samples: Samples | None = None) -> Samples:
    """Parses the whole log at once, so a measurement the console wrapped onto two lines counts."""
    if samples is None:
        samples = Samples()
    for match in FRAME_TO.finditer(text):
        name, source = f"frame to {' '.join(match[1].split())}", match[3]
        samples.add(Kind(name, source), match[2])
        samples.add(Kind(name, source, "noticed"), match[4])
        samples.add(Kind(name, source, "spoke"), match[5])
    for match in EVENT_TO_BARK.finditer(text):
        samples.add(Kind("event to bark"), match[1])
        if match[2]:
            samples.add(Kind("event to bark", match[2]), match[1])
    for name, pattern in SIMPLE_KINDS.items():
        for match in pattern.finditer(text):
            samples.add(Kind(name), match[1])
    samples.stalls += [float(match[1]) for match in STALLED.finditer(text)]
    for match in LONGEST.finditer(text):
        samples.longest.append(float(match[1]))
        samples.watched_s.append(float(match[2]))
    return samples


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile of a non-empty list; with one value, every percentile is it."""
    if not values:
        raise ValueError("percentile of no values")
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def table_rows(samples: Samples) -> list[tuple[str, int, int, int, int]]:
    """Label, count, p50, p95 and max in whole milliseconds, for each kind that has data."""
    return [
        (
            kind.label(),
            len(values),
            round(percentile(values, 50)),
            round(percentile(values, 95)),
            round(max(values)),
        )
        for kind, values in sorted(samples.latency.items(), key=lambda item: item[0].sort_key())
    ]


def loop_line(samples: Samples) -> str | None:
    if not (samples.stalls or samples.longest):
        return None
    longest = round(max(samples.stalls + samples.longest))
    line = f"Event loop: {len(samples.stalls)} stalls over {WARN_MS:.0f} ms, longest {longest} ms"
    if samples.watched_s:
        line += f", over {sum(samples.watched_s):.0f} s watched"
    return line + "."


def render(samples: Samples) -> str:
    lines: list[str] = []
    rows = table_rows(samples)
    if rows:
        lines += ["| Kind | Count | p50 ms | p95 ms | Max ms |", "|---|---:|---:|---:|---:|"]
        lines += [f"| {' | '.join(str(cell) for cell in row)} |" for row in rows]
    loop = loop_line(samples)
    if loop:
        lines += ["", loop] if rows else [loop]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="latency_report", description="Summarise Latency: lines from saved brain logs."
    )
    parser.add_argument("logs", nargs="*", default=["-"], help="log files; - or none for stdin")
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    except SystemExit as stop:
        # argparse exits 0 for --help and 2 for bad arguments; return rather than exit, for tests.
        return FOUND if stop.code == 0 else UNREADABLE

    samples = Samples()
    for name in args.logs or ["-"]:
        try:
            data = sys.stdin.buffer.read() if name == "-" else Path(name).read_bytes()
        except OSError as error:
            print(f"latency_report: can't read {name}: {error}", file=sys.stderr)
            return UNREADABLE
        parse_text(decode_log(data), samples)

    if samples.empty():
        print("No latency or event loop lines found.")
        return NOTHING_MATCHED
    print(render(samples))
    return FOUND


if __name__ == "__main__":
    sys.exit(main())
