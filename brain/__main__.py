"""Entry point: `python -m brain --live` or `python -m brain --replay <session-dir>`."""

import argparse
import asyncio
import logging
from pathlib import Path

from brain.app import run
from brain.config import Settings
from brain.logging_setup import configure_logging

log = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(prog="brain")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true", help="capture the live screen")
    mode.add_argument("--replay", type=Path, metavar="SESSION_DIR", help="feed a recorded session")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show debug and library log lines"
    )
    args = parser.parse_args()

    configure_logging(args.verbose)
    try:
        asyncio.run(run(Settings(), replay_dir=args.replay))
    except KeyboardInterrupt:
        log.info("Stopped by user")


if __name__ == "__main__":
    main()
