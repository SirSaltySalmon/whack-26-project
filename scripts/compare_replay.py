"""Compares two runs' sent messages, ignoring timing, IDs and rectangles.

Usage: python scripts/compare_replay.py a/messages.jsonl b/messages.jsonl
Either argument can also be a session directory. Exits 0 when they match, 1 when they differ (with
a diff of the normalized messages) and 2 on a usage error or a missing file.
"""

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brain.replay.compare import main  # noqa: E402

if __name__ == "__main__":
    # Shows read_jsonl's warning when a line is skipped, such as one cut short by a crash.
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(main(sys.argv[1:]))
