"""The partner hearing itself through the mic, using lines from a live test where it looped."""

from brain.voice.self_echo import ECHO_WINDOW_S, SelfEcho


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def echo_after(said: str) -> tuple[SelfEcho, Clock]:
    clock = Clock()
    echo = SelfEcho(clock)
    echo.said(said)
    clock.now += 3
    return echo, clock


def test_the_partners_line_heard_back_is_an_echo() -> None:
    echo, _ = echo_after("I can't check that right now.")
    assert echo.is_echo("I can't check that right now.")


def test_a_cut_off_echo_still_counts() -> None:
    echo, _ = echo_after("We can smash it and see what loot drops out.")
    assert echo.is_echo("We can smash it and see what's")


def test_a_misheard_echo_mostly_matching_counts() -> None:
    echo, _ = echo_after("My bad, I'll let you finish and keep it smooth from now on.")
    assert echo.is_echo("My bad. I'll let you finish and keep it smooth from now on.")


def test_the_player_answering_isnt_an_echo() -> None:
    echo, _ = echo_after("What are you aiming to do first in this world?")
    assert not echo.is_echo("I want to build a house near the trees")


def test_the_player_reusing_a_few_words_isnt_an_echo() -> None:
    echo, _ = echo_after("Nice little base here, what do you want to build first?")
    assert not echo.is_echo("I want to build a tower first")


def test_short_turns_always_go_through() -> None:
    echo, _ = echo_after("Want to look closer?")
    assert not echo.is_echo("look closer")


def test_an_old_line_no_longer_counts() -> None:
    echo, clock = echo_after("I can't check that right now.")
    clock.now += ECHO_WINDOW_S
    assert not echo.is_echo("I can't check that right now.")


def test_nothing_said_means_no_echo() -> None:
    assert not SelfEcho().is_echo("What do you see on the screen?")
