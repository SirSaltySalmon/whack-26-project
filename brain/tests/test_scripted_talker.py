import asyncio
from pathlib import Path

import pytest

from brain.capture.ring_buffer import RingBuffer
from brain.director.director import Director
from brain.director.talker import reply
from brain.events import EventBus
from brain.llm.base import LLMUnavailableError
from brain.replay.format import PARTNER_SAID
from brain.replay.scripted import ScriptedTalker, partner_lines
from brain.replay.source import ReplayLoop
from brain.tests.director_rig import BOOK, settle
from brain.tests.fakes import FakeOverlay, FakeVoice
from brain.tests.replay_rig import RigFrame, RigSession, event, message, solid_image, write_session


async def take(talker: ScriptedTalker) -> list[str]:
    return [chunk async for chunk in talker.stream_text("system", "prompt", 200)]


async def test_lines_come_out_in_order_then_run_out() -> None:
    talker = ScriptedTalker(["Nice dodge.", "That one hurt."])
    assert talker.remaining == 2

    assert await take(talker) == ["Nice dodge."]
    assert talker.remaining == 1
    assert await take(talker) == ["That one hurt."]
    assert talker.remaining == 0
    with pytest.raises(LLMUnavailableError):
        await take(talker)


async def test_the_talker_says_the_line_then_stays_quiet() -> None:
    talker = ScriptedTalker(["Looks like a slime."])

    assert await reply(talker, "what's that?", "supportive", 100) == "Looks like a slime."
    assert await reply(talker, "and that?", "supportive", 100) is None


def test_partner_lines_leave_out_questions_only_as_often_as_asked(tmp_path: Path) -> None:
    question = "Is that your base?"
    session = RigSession(
        events=[
            event(0.5, PARTNER_SAID, text=question),
            event(1.0, "PlayerSpeech", transcript="what's that?"),
            event(1.5, PARTNER_SAID, text="Looks like a slime."),
            # The same words again, but as a reply this time, so they stay.
            event(2.0, PARTNER_SAID, text=question),
            event(2.5, PARTNER_SAID),
        ],
        messages=[
            message(0.4, type="question.ask", question_id="q1", text=question),
            message(1.6, type="subtitle.chunk", utterance_id="u1", text="Looks like a slime."),
        ],
    )

    assert partner_lines(write_session(tmp_path, session)) == ["Looks like a slime.", question]


def test_a_missing_session_has_no_lines(tmp_path: Path) -> None:
    assert partner_lines(tmp_path / "nowhere") == []


async def test_a_replay_drives_the_director_to_say_the_recorded_line(tmp_path: Path) -> None:
    """WP3's done-when: replayed speech, a real director, and the line the partner said."""
    question = "Is that your base?"
    session = write_session(
        tmp_path,
        RigSession(
            frames=[RigFrame(0.0, solid_image())],
            events=[
                event(0.3, PARTNER_SAID, text=question),
                event(1.0, "PlayerStartedSpeaking"),
                event(1.5, "PlayerSpeech", transcript="what's that?"),
                event(2.0, PARTNER_SAID, text="Looks like a slime."),
            ],
            messages=[message(0.2, type="question.ask", question_id="q1", text=question)],
            settings={"personality": "calm"},
        ),
    )
    bus, voice, link = EventBus(), FakeVoice(), FakeOverlay()
    talker = ScriptedTalker(partner_lines(session))
    director = Director(
        bus,
        voice,
        proactive=lambda: link.settings.proactive,
        talker=talker,
        personality=lambda: link.settings.personality,
        personalities=BOOK,
    )
    task = asyncio.create_task(director.run())
    try:
        # The session lasts 2 s, so this plays it in about 2 ms of real time.
        await ReplayLoop(session, RingBuffer(4), bus, link, speed=1000.0).run()
        await settle()
        assert link.settings.personality == "calm"
        assert voice.said == ["Looks like a slime."]
        assert talker.remaining == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
