"""Entry point: `python -m brain --live` or `python -m brain --replay <session-dir>`.

Add `--type` to take player turns typed on stdin as well, which needs no mic or Deepgram key.
Add `--record` to a live run to save a session for replay. It stores screen data, so it's never on
by default.
"""

import argparse
import asyncio
import logging
from pathlib import Path

from brain.app import run
from brain.config import Settings
from brain.logging_setup import configure_logging

log = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
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
        "--record",
        action="store_true",
        help="live only: save frames, events and messages under sessions/ for replay",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="replay only: play the session this many times faster",
    )
    parser.add_argument(
        "--exit-when-done",
        action="store_true",
        help="replay only: stop once the session has played",
    )
    parser.add_argument(
        "--write-messages",
        type=Path,
        metavar="PATH",
        help="replay only: save every message sent to the overlay, for scripts/compare_replay.py",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show debug and library log lines"
    )
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    if args.record and args.replay:
        parser.error("--record only works with --live")
    replay_only = args.speed != 1.0 or args.exit_when_done or args.write_messages
    if replay_only and not args.replay:
        parser.error("--speed, --exit-when-done and --write-messages only work with --replay")
    if args.speed <= 0:
        parser.error("--speed must be above 0")

    configure_logging(args.verbose)
    try:
        asyncio.run(
            run(
                Settings(),
                replay_dir=args.replay,
                typed=args.typed,
                record=args.record,
                speed=args.speed,
                exit_when_done=args.exit_when_done,
                write_messages=args.write_messages,
            )
        )
    except KeyboardInterrupt:
        log.info("Stopped by user")


if __name__ == "__main__":
    main()
