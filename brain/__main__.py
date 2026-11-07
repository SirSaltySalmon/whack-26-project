"""Entry point: `python -m brain --live` or `python -m brain --replay <session-dir>`.

Add `--type` to take player turns typed on stdin as well, which needs no mic or Deepgram key.
"""

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
        "--type",
        action="store_true",
        dest="typed",
        help="also take player turns typed on stdin, such as `5: what's that` to wait 5 s first",
    )
    parser.add_argument(
        "--debug-regions",
        action="store_true",
        help="draw the learned HUD regions over the game, with what each reader reads",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show debug and library log lines"
    )
    args = parser.parse_args()

    configure_logging(args.verbose)
    try:
        settings = Settings()
        if args.debug_regions:
            settings = settings.model_copy(update={"debug_regions": True})
        asyncio.run(run(settings, replay_dir=args.replay, typed=args.typed))
    except KeyboardInterrupt:
        log.info("Stopped by user")


if __name__ == "__main__":
    main()
