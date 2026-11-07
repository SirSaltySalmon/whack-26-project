"""Writes a memory database out as the fixed starting point for replay runs.

The snapshot includes conversation transcripts. Read it before committing it, and only snapshot a
session you'd be happy to publish. If it's used on stage, say that its memory was seeded.

Usage: python -m scripts.snapshot_memory [database] [output]
"""

import argparse
import logging
from pathlib import Path

from brain.config import Settings
from brain.memory.db import connect
from brain.memory.snapshot import dump_snapshot

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", nargs="?", type=Path, default=settings.db_path)
    parser.add_argument("output", nargs="?", type=Path, default=settings.replay_snapshot)
    args = parser.parse_args()

    if not args.database.exists():
        # connect() would otherwise create an empty database and snapshot that.
        parser.error(f"{args.database} doesn't exist")
    conn = connect(args.database)
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(dump_snapshot(conn), encoding="utf-8", newline="\n")
    finally:
        conn.close()
    log.info("Wrote %s. It may contain transcripts, so read it before committing.", args.output)


if __name__ == "__main__":
    main()
