from collections.abc import AsyncIterator

from brain.director.director import Director
from brain.director.rules import AskTalker
from brain.director.talker import cap_words, reply
from brain.events import EventBus
from brain.llm.base import LLMUnavailableError


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

    async def say(self, text: str) -> None:
        self.said.append(text)

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
