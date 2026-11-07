from collections.abc import AsyncIterator

from brain.director.director import Director
from brain.director.rules import AskTalker, ReactToEvent
from brain.director.talker import cap_words, reply
from brain.events import EventBus
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

    async def say(self, text: str) -> bool:
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
