"""Entry point: `python -m brain --live` or `python -m brain --replay <session-dir>`.

Add `--type` to take player turns typed on stdin as well, which needs no mic or Deepgram key.
Add `--record` to a live run to save a session for replay. It stores screen data, so it's never on
by default. `--describe` prints what the Control Center can offer, as JSON, and exits.
Add `--off observer,tts` to turn parts off while testing; DISABLE in .env does the same.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from brain.config import Settings
from brain.logging_setup import configure_logging
from brain.switches import PARTS, apply_off, parse_off

log = logging.getLogger(__name__)


async def run(settings: Settings, **options: Any) -> None:
    """Imports the brain on first use: it takes seconds, and --describe must answer in one."""
    from brain.app import run as run_brain

    await run_brain(settings, **options)


def _off_parts(text: str) -> set[str]:
    try:
        return parse_off(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brain")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true", help="capture the live screen")
    mode.add_argument("--replay", type=Path, metavar="SESSION_DIR", help="feed a recorded session")
    mode.add_argument(
        "--describe",
        action="store_true",
        help="print personalities, voices and which keys are set, as JSON, then exit",
    )
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
        "--off",
        type=_off_parts,
        default=set(),
        metavar="PARTS",
        help="turn parts off for this run, comma-separated: "
        + "; ".join(f"{name} ({what})" for name, what in PARTS.items()),
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show debug and library log lines"
    )
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    try:
        settings = apply_off(Settings(), args.off)
    except ValueError as exc:
        # A bad DISABLE in .env, since --off is checked by the parser.
        parser.error(f"DISABLE: {exc}")
    if args.describe:
        from brain.describe import describe

        # Stdout is the interface here: the Control Center reads this one JSON line.
        sys.stdout.write(describe(settings).model_dump_json() + "\n")
        return
    if args.record and args.replay:
        parser.error("--record only works with --live")
    replay_only = args.speed != 1.0 or args.exit_when_done or args.write_messages
    if replay_only and not args.replay:
        parser.error("--speed, --exit-when-done and --write-messages only work with --replay")
    if args.speed <= 0:
        parser.error("--speed must be above 0")

    configure_logging(args.verbose)
    if settings.disable:
        log.info("Turned off for this run: %s", settings.disable.replace(",", ", "))
    try:
        game_hint = ""
        if args.live:
            from brain.game_setup import pick_game

            # Before the event loop, because it can wait on the terminal.
            settings, game_hint = pick_game(settings)
        if args.debug_regions:
            settings = settings.model_copy(update={"debug_regions": True})
        asyncio.run(
            run(
                settings,
                replay_dir=args.replay,
                typed=args.typed,
                record=args.record,
                speed=args.speed,
                exit_when_done=args.exit_when_done,
                write_messages=args.write_messages,
                game_hint=game_hint,
            )
        )
    except KeyboardInterrupt:
        log.info("Stopped by user")


if __name__ == "__main__":
    main()
