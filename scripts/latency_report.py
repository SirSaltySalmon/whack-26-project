"""Summarize brain latency samples. Usage: python scripts/latency_report.py run.log"""

import argparse
import re
from collections import defaultdict
from math import ceil
from pathlib import Path

SAMPLE = re.compile(
    r"Latency:\s*(event\s+to\s+bark|frame\s+to\s+bark|end\s+of\s+turn\s+to\s+first\s+audio|"
    r"player\s+turn\s+took)\s+(\d+(?:\.\d+)?)\s*ms\b(?:\s*\(([\w.-]+)\))?"
)


def samples(log: str) -> dict[str, list[float]]:
    groups: dict[str, list[float]] = defaultdict(list)
    for match in SAMPLE.finditer(log):
        kind = " ".join(match[1].split())
        value = float(match[2])
        groups[kind].append(value)
        if kind.endswith("to bark") and match[3]:
            groups[f"{kind} ({match[3]})"].append(value)
    return groups


def report(log: str) -> str:
    rows = ["| Latency | Count | p50 (ms) | p95 (ms) | Max (ms) |", "|---|---:|---:|---:|---:|"]
    for kind, values in sorted(samples(log).items()):
        ordered = sorted(values)
        n = len(ordered)
        # Nearest-rank percentiles report an actual measured latency.
        p50, p95 = (ordered[ceil(p * n) - 1] for p in (0.5, 0.95))
        rows.append(f"| {kind} | {n} | {p50:g} | {p95:g} | {ordered[-1]:g} |")
    return "\n".join(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    path = parser.parse_args().log
    raw = path.read_bytes()
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    print(report(raw.decode(encoding, errors="replace")))
