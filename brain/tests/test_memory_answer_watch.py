"""When to give up on the question just asked. Pure state, driven by a fake clock."""

from brain.memory.asking import AnswerWatch
from shared.protocol.messages import Settings


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_the_wait_restarts_when_a_reply_starts_or_a_turn_ends() -> None:
    clock = Clock()
    watch = AnswerWatch(clock, answer_timeout_s=20.0)
    watch.asked(7)
    clock.now += 19
    assert watch.overdue() is None
    watch.reply_started()
    clock.now += 19
    assert watch.overdue() is None
    assert watch.turn_ended() is None
    clock.now += 19.9
    assert watch.overdue() is None
    clock.now += 0.1
    give_up = watch.overdue()
    assert give_up is not None and give_up[0] == 7 and "20 s" in give_up[1]
    assert watch.pending is None
    # A late answer with no id still lands on it.
    assert watch.last_asked == 7


def test_typed_replies_get_the_longer_timeout() -> None:
    clock = Clock()
    watch = AnswerWatch(clock, answer_timeout_s=20.0, typed_timeout_s=45.0)
    watch.follow(Settings(mic_enabled=False))
    watch.asked(1)
    clock.now += 44
    assert watch.overdue() is None
    clock.now += 1
    assert watch.overdue() is not None
    # Settings without the field, such as an older model, mean the mic is on.
    watch.follow(object())
    assert watch.mic_enabled is True


def test_more_turns_than_allowed_give_up_and_settling_forgets_it() -> None:
    watch = AnswerWatch(Clock(), max_turns=2)
    watch.asked(3)
    assert watch.turn_ended() is None
    assert watch.turn_ended() is None
    assert watch.turn_ended() == (3, "3 player turns went by without an answer")
    watch.asked(4)
    watch.settled(4)
    assert watch.pending is None and watch.last_asked is None


def test_nothing_happens_with_nothing_asked() -> None:
    watch = AnswerWatch(Clock())
    watch.reply_started()
    assert watch.turn_ended() is None
    assert watch.overdue() is None
    watch.settled(9)
    assert watch.pending is None
