"""A bare "okay" or "thanks" isn't answered, unless it may answer something or resume a turn."""

import pytest

from brain.director.acks import only_acknowledges
from brain.director.rules import AskTalker, DirectorState, PartnerSpoke, decide
from brain.events import PlayerSpeech


@pytest.mark.parametrize(
    "transcript",
    ["Good.", "Sorry.", "Alright.", "okay", "Oh, thanks!", "Thank you.", "alright cool", "Mhm."],
)
def test_bare_acknowledgements_are_recognised(transcript: str) -> None:
    assert only_acknowledges(transcript)


@pytest.mark.parametrize(
    "transcript",
    [
        "",
        "Okay?",  # A question, even if it's one word.
        "Yes.",  # Yes and no answer questions, which may have been asked lines ago.
        "No.",
        "yeah",
        "Okay, what's next",
        "Thanks, now show me the anvil.",
        "good good good good good",  # Too long to be just a nod.
        "I forgot it",
    ],
)
def test_anything_more_than_an_acknowledgement_is_not_one(transcript: str) -> None:
    assert not only_acknowledges(transcript)


def answered(state: DirectorState) -> DirectorState:
    """The partner has replied with a statement, so nothing is waiting on the player."""
    decide(PartnerSpoke(ts=1.0), state)
    return state


def test_an_acknowledgement_after_a_statement_gets_no_reply() -> None:
    state = answered(DirectorState())
    assert decide(PlayerSpeech(transcript="Alright.", ts=2.0), state) == []
    # The player still talked, so a question or tip waits as it would after any turn.
    assert state.last_talk_at == 2.0


def test_an_acknowledgement_after_a_question_is_answered() -> None:
    state = DirectorState()
    decide(PartnerSpoke(asked=True, ts=1.0), state)
    assert decide(PlayerSpeech(transcript="Okay.", ts=2.0), state) == [AskTalker("Okay.")]


def test_an_acknowledgement_while_a_turn_waits_for_its_reply_is_answered() -> None:
    # Its start cancelled that reply, so answering it resumes the cut-off turn (carry.py).
    state = answered(DirectorState())
    decide(PlayerSpeech(transcript="What's that enemy?", ts=2.0), state)
    assert decide(PlayerSpeech(transcript="Okay.", ts=3.0), state) == [AskTalker("Okay.")]


def test_once_the_partner_replies_the_next_acknowledgement_is_let_be() -> None:
    state = answered(DirectorState())
    decide(PlayerSpeech(transcript="What's that enemy?", ts=2.0), state)
    decide(PartnerSpoke(ts=3.0), state)
    assert decide(PlayerSpeech(transcript="Thanks!", ts=4.0), state) == []


def test_a_real_turn_is_always_answered() -> None:
    state = answered(DirectorState())
    event = PlayerSpeech(transcript="Okay, where do I go now?", ts=2.0)
    assert decide(event, state) == [AskTalker("Okay, where do I go now?")]
