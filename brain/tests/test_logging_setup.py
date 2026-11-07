import logging

from brain.logging_setup import CHATTY_LIBRARIES, configure_logging


def test_quiet_by_default_keeps_our_info_but_not_request_lines() -> None:
    configure_logging()
    assert logging.getLogger("brain").getEffectiveLevel() == logging.INFO
    for name in CHATTY_LIBRARIES:
        assert logging.getLogger(name).getEffectiveLevel() == logging.WARNING


def test_verbose_shows_our_debug_and_request_lines() -> None:
    configure_logging(verbose=True)
    assert logging.getLogger("brain").getEffectiveLevel() == logging.DEBUG
    for name in CHATTY_LIBRARIES:
        assert logging.getLogger(name).getEffectiveLevel() == logging.INFO
    configure_logging()
