import logging
import sys

from loguru import logger as pipecat_logger

QUIET_FORMAT = "%(asctime)s %(message)s"
VERBOSE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
QUIET_TIME = "%H:%M:%S"

# These log a line per request, and the observer sends a request every 0.8 s.
CHATTY_LIBRARIES = ("httpx", "httpx2", "httpcore", "websockets")


def configure_logging(verbose: bool = False) -> None:
    """Quiet by default, so the player's words stand out. Warnings and errors always show."""
    logging.basicConfig(
        level=logging.INFO,
        format=VERBOSE_FORMAT if verbose else QUIET_FORMAT,
        datefmt=None if verbose else QUIET_TIME,
    )
    logging.getLogger("brain").setLevel(logging.DEBUG if verbose else logging.INFO)
    for name in CHATTY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.INFO if verbose else logging.WARNING)

    # Pipecat logs through loguru, which ignores the settings above and defaults to DEBUG.
    pipecat_logger.remove()
    pipecat_logger.add(sys.stderr, level="DEBUG" if verbose else "WARNING")
