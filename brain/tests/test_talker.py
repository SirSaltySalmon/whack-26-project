from collections.abc import AsyncIterator

import pytest

from brain.director.director import Director
from brain.director.rules import AskTalker, ReactToEvent
from brain.director.talker import ADVICE_PROMPT, SKIP, build_system, cap_words, is_skip, reply
from brain.events import EventBus
from brain.latency import Origin
from brain.llm.base import LLMUnavailableError
from brain.memory.context import CONTEXT_PREAMBLE


class FakeLLM:
    def __init__(self, chunks: list[str], fail: bool = False) -> None:
        self.chunks = chunks
        self.fail = fail
        self.system = ""

    async def stream_text(self, system: str, prompt: str, max_tokens: int) -> AsyncIterator[str]:
        self.system = system
        if self.fail:
            raise LLMUnavailableError("over quota")
        for chunk in self.chunks:
            yield chunk


class FakeVoice:
    def __init__(self) -> None:
        self.said: list[str] = []

    async def say(self, text: str, *, origin: Origin | None = None) -> bool:
        self.said.append(text)
        return True

    async def set_voice(self, voice_id: str | None) -> None:
        return

    async def run(self) -> None:
        return


def test_cap_words_keeps_short_replies_whole() -> None:
    assert cap_words("  Nice dodge!  ", 12) == "Nice dodge!"


def test_cap_words_clips_and_ends_the_sentence() -> None:
    assert cap_words("one two three, four five", 3) == "one two three."


async def test_reply_is_capped_and_uses_the_personality() -> None:
    llm = FakeLLM(["That boss ", "hits hard, so keep ", "moving and dodge left now please"])
    text = await reply(llm, "tips?", personality="snarky", max_words=6)
    assert text == "That boss hits hard, so keep."
    assert "snarky" in llm.system


async def test_reply_stays_quiet_when_the_llm_is_unavailable() -> None:
    assert await reply(FakeLLM([], fail=True), "hi", "supportive", 12) is None


async def test_director_speaks_the_talker_reply() -> None:
    voice = FakeVoice()
    director = Director(EventBus(), voice, proactive=lambda: True, talker=FakeLLM(["Hi there!"]))
    await director._perform(AskTalker("hello"))
    assert voice.said == ["Hi there!"]


async def test_director_without_a_talker_stays_quiet() -> None:
    voice = FakeVoice()
    director = Director(EventBus(), voice, proactive=lambda: True)
    await director._perform(AskTalker("hello"))
    assert voice.said == []


async def test_reply_gets_the_context_and_its_warning() -> None:
    llm = FakeLLM(["Hi."])
    await reply(llm, "hello", "supportive", 12, context="NOW: danger: high")
    assert "NOW: danger: high" in llm.system and CONTEXT_PREAMBLE in llm.system


async def test_director_passes_live_context_and_records_what_it_said() -> None:
    llm = FakeLLM(["Hi there!"])
    voice = FakeVoice()
    spoken: list[str] = []
    queries: list[str] = []

    async def context(query: str) -> str:
        queries.append(query)
        return "NOW: player mood: frustrated"

    async def on_spoken(text: str) -> None:
        spoken.append(text)

    director = Director(
        EventBus(), voice, proactive=lambda: True, talker=llm, context=context, on_spoken=on_spoken
    )
    await director._perform(AskTalker("hello"))
    assert "player mood: frustrated" in llm.system
    assert queries == ["hello"] and spoken == ["Hi there!"]


async def test_a_context_failure_still_gets_a_reply() -> None:
    async def broken(_: str) -> str:
        raise RuntimeError("database locked")

    voice = FakeVoice()
    director = Director(
        EventBus(), voice, proactive=lambda: True, talker=FakeLLM(["Hi."]), context=broken
    )
    await director._perform(AskTalker("hello"))
    assert voice.said == ["Hi."]


async def test_director_reacts_to_game_events_through_the_talker() -> None:
    prompts: list[str] = []

    class Recording(FakeLLM):
        async def stream_text(
            self, system: str, prompt: str, max_tokens: int
        ) -> AsyncIterator[str]:
            prompts.append(prompt)
            yield "That looks rough."

    voice = FakeVoice()
    director = Director(EventBus(), voice, proactive=lambda: True, talker=Recording([]))
    await director._perform(ReactToEvent("danger_started", {"threats": ["Wall of Flesh"]}))
    assert voice.said == ["That looks rough."]
    assert "danger started" in prompts[0] and "Wall of Flesh" in prompts[0]
    assert "can be wrong" in prompts[0]


def test_prompt_keeps_replies_short_but_allows_detail_on_request() -> None:
    system = build_system("supportive", "", 100, "")
    assert "about 12 words" in system
    assert "explain, elaborate or give details" in system
    assert "under 100 words" in system


def test_a_long_requested_answer_is_kept_whole_up_to_the_cap() -> None:
    long_answer = " ".join(["word"] * 60) + "."
    assert cap_words(long_answer, 100) == long_answer
    assert len(cap_words(" ".join(["word"] * 150), 100).split()) == 100


def test_the_tip_prompt_never_asks_and_grounds_the_tip_in_what_memory_knows() -> None:
    # Questions have their own budget and timeout, and a tip that asked would dodge both.
    assert "?" not in ADVICE_PROMPT and "Don't ask" in ADVICE_PROMPT
    for section in ("PLAYER", "GAME", "NOW"):
        assert section in ADVICE_PROMPT
    assert "don't guess" in ADVICE_PROMPT and SKIP in ADVICE_PROMPT


@pytest.mark.parametrize(
    ("text", "skips"),
    [("SKIP", True), ("skip.", True), (" Skip! ", True), ("Skip the boss for now.", False)],
)
def test_only_a_bare_skip_counts_as_skipping(text: str, skips: bool) -> None:
    assert is_skip(text) is skips


def test_narration_about_the_player_is_never_spoken() -> None:
    from brain.director.talker import drop_narration

    # From a live run: the advice line opened with the model's reasoning.
    leaked = (
        "The player's on the character select screen, so there's no progress to build on yet. "
        "Pick a character from the list and hit Play to dive in."
    )
    assert drop_narration(leaked) == "Pick a character from the list and hit Play to dive in."
    assert drop_narration("Nice dodge! Watch that slime.") == "Nice dodge! Watch that slime."
    # "player" on its own, such as another player, is fine; only "the player" is narration.
    assert drop_narration("Another player built that.") == "Another player built that."
    assert drop_narration("The player is low on health.") == ""


async def test_a_reply_that_is_only_narration_stays_quiet() -> None:
    llm = FakeLLM(["The player seems to be exploring."])
    assert await reply(llm, "hi", "supportive", 12) is None
