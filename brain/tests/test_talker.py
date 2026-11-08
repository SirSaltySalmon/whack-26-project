from collections.abc import AsyncIterator, Sequence

import pytest

from brain.director.director import Director
from brain.director.rules import AskTalker, ReactToEvent
from brain.director.talker import (
    ADVICE_PROMPT,
    SKIP,
    build_system,
    cap_words,
    drop_narration,
    is_skip,
    reply,
    wants_detail,
)
from brain.events import EventBus
from brain.latency import Origin
from brain.llm.base import ChatTurn, LLMUnavailableError, System, system_text
from brain.memory.context import CONTEXT_PREAMBLE
from brain.memory.layers import TalkerContext


class FakeLLM:
    def __init__(self, chunks: list[str], fail: bool = False) -> None:
        self.chunks = chunks
        self.fail = fail
        self.system = ""
        self.prompt = ""
        self.history: tuple[ChatTurn, ...] = ()

    async def stream_text(
        self, system: System, prompt: str, max_tokens: int, history: Sequence[ChatTurn] = ()
    ) -> AsyncIterator[str]:
        self.system = system_text(system)
        self.prompt = prompt
        self.history = tuple(history)
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


async def test_reply_gets_memory_the_conversation_and_live_with_their_warning() -> None:
    llm = FakeLLM(["Hi."])
    history = (ChatTurn("assistant", "Ready?"), ChatTurn("user", "yes"))
    context = TalkerContext("GAME: Terraria", history, "NOW: danger: high")
    await reply(llm, "hello", "supportive", 12, context=context)
    assert "GAME: Terraria" in llm.system and CONTEXT_PREAMBLE in llm.system
    assert "NOW: danger: high" not in llm.system and llm.prompt == context.message("hello")
    assert llm.history == history


async def test_director_passes_live_context_and_records_what_it_said() -> None:
    llm = FakeLLM(["Hi there!"])
    voice = FakeVoice()
    spoken: list[str] = []
    queries: list[str] = []

    async def context(query: str, current: str | None) -> TalkerContext:
        queries.append(query)
        assert current == "hello"
        return TalkerContext(live="NOW: player mood: frustrated")

    async def on_spoken(text: str) -> None:
        spoken.append(text)

    director = Director(
        EventBus(), voice, proactive=lambda: True, talker=llm, context=context, on_spoken=on_spoken
    )
    await director._perform(AskTalker("hello"))
    assert "player mood: frustrated" in llm.prompt
    assert queries == ["hello"] and spoken == ["Hi there!"]


async def test_a_context_failure_still_gets_a_reply() -> None:
    async def broken(_: str, __: str | None) -> TalkerContext:
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
            self,
            system: System,
            prompt: str,
            max_tokens: int,
            history: Sequence[ChatTurn] = (),
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
    brief = system_text(build_system("supportive", "", 100, ""))
    assert "about 12 words" in brief
    # Naming the 100-word ceiling on every turn pulled replies toward it.
    assert "100" not in brief
    assert "up to 100 words" in system_text(build_system("supportive", "", 100, "", detail=True))


def test_prompt_says_what_to_write_rather_than_forbidding_explanations() -> None:
    # With thinking off, a rule against describing the reply made reasoning leak more.
    system = system_text(build_system("supportive", "", 100, ""))
    assert "Never describe what you're about to say" not in system
    assert "internal or system XML tags" in system and "<thinking>" not in system
    assert "leave out offers of more help" in system


@pytest.mark.parametrize(
    ("transcript", "detail"),
    [
        ("Can you explain how this works?", True),
        ("Tell me more about the boss", True),
        ("walk me through the recipe", True),
        ("Give me the full list", True),
        ("What's going on?", False),
        ("What's that enemy?", False),
        ("How do I beat it?", False),
    ],
)
def test_only_asking_for_more_counts_as_wanting_detail(transcript: str, detail: bool) -> None:
    assert wants_detail(transcript) is detail


LONG = "This is one sentence that runs to twelve words or so in all. " * 4


async def test_a_reply_is_cut_to_whole_brief_sentences_unless_detail_was_asked() -> None:
    brief = await reply(FakeLLM([LONG]), "what's that?", "supportive", 100)
    assert brief == " ".join(LONG.split()[:26])  # Two whole 13-word sentences fit in 30.
    detailed = await reply(FakeLLM([LONG]), "explain", "supportive", 100, detail=True)
    assert detailed == " ".join(LONG.split())


def test_cap_words_keeps_whole_sentences_that_fit() -> None:
    assert cap_words("Nice. That was close, really close. Keep going.", 5) == "Nice."
    assert cap_words("Nice dodge. Again!", 3) == "Nice dodge. Again!"


async def test_a_stream_stopped_mid_sentence_keeps_only_finished_sentences() -> None:
    llm = FakeLLM(["Watch out. ", "That slime is ", "about to jump on you from the left side now"])
    assert await reply(llm, "hi", "supportive", 8) == "Watch out."


@pytest.mark.parametrize(
    "leaked",
    [
        "Under NOW it says you're in a forest.",
        "PLAYER shows you're in survival.",
        "I'll call look_closer to check.",
        "The user wants a tip.",
    ],
)
def test_sentences_about_the_context_or_tools_are_never_spoken(leaked: str) -> None:
    from brain.director.talker import drop_narration

    assert drop_narration(f"{leaked} Nice spot.") == "Nice spot."
    assert drop_narration(f"Nice spot. {leaked}") == "Nice spot."


def test_shouting_now_is_still_spoken() -> None:
    from brain.director.talker import drop_narration

    assert drop_narration("Run NOW! It's right behind you.") == "Run NOW! It's right behind you."


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
    # Facts in the wiki's own words are kept, even as the whole answer.
    wiki = "The player can craft a workbench from wood. You'll need ten."
    assert drop_narration(wiki) == wiki
    assert drop_narration("The player must defeat the boss first.") != ""
    # Only the opening is checked, where reasoning leaks; later lines are the answer.
    later = "Good news. The player is immune to lava with that charm."
    assert drop_narration(later) == later
    opening = "The player is new. The player has no gear yet. Grab some wood first."
    assert drop_narration(opening) == "Grab some wood first."


async def test_a_reply_that_is_only_narration_stays_quiet() -> None:
    llm = FakeLLM(["The player seems to be exploring."])
    assert await reply(llm, "hi", "supportive", 12) is None


async def test_reactions_and_replies_share_one_conversation() -> None:
    llm = FakeLLM(["Okay."])
    history = (ChatTurn("assistant", "Want to fight the boss?"), ChatTurn("user", "not yet"))
    currents: list[str | None] = []

    async def context(query: str, current: str | None) -> TalkerContext:
        currents.append(current)
        return TalkerContext(history=history)

    director = Director(
        EventBus(), FakeVoice(), proactive=lambda: True, talker=llm, context=context
    )
    await director._perform(ReactToEvent("danger_started", {"threats": ["Slime"]}))
    assert llm.history == history
    await director._perform(AskTalker("hello"))
    assert llm.history == history
    # Only the player's turn has words being answered, to leave out of the conversation.
    assert currents == [None, "hello"]


def test_a_copied_conversation_note_is_never_said() -> None:
    text = "(note, 12:40 into the session) you looked closer: a Copper Pickaxe. Nice pick!"
    assert drop_narration(text) == "Nice pick!"


def test_in_danger_the_prompt_asks_for_callouts() -> None:
    calm = system_text(build_system("supportive", "", 100, ""))
    urgent = system_text(build_system("supportive", "", 100, "", urgent=True))
    assert "mid-fight" not in calm
    assert "mid-fight" in urgent and "about 6 words" in urgent and "under 25 words" in urgent


async def test_in_danger_even_a_requested_explanation_is_cut_short() -> None:
    llm = FakeLLM([" ".join(["word"] * 60)])
    # The caller reads detail from their words, so this is "explain" asked mid-fight.
    text = await reply(llm, "explain", "supportive", max_words=100, detail=True, urgent=True)
    assert text is not None and len(text.split()) == 25


async def test_the_director_hurries_only_while_the_player_is_in_danger() -> None:
    systems: list[str] = []

    class Recording(FakeLLM):
        async def stream_text(
            self, system: System, prompt: str, max_tokens: int, history: Sequence[ChatTurn] = ()
        ) -> AsyncIterator[str]:
            systems.append(system_text(system))
            yield "Behind you!"

    director = Director(EventBus(), FakeVoice(), proactive=lambda: True, talker=Recording([]))
    await director._perform(ReactToEvent("item_found", {}))
    director._state.in_danger = True
    await director._perform(ReactToEvent("danger_started", {}))
    assert "mid-fight" not in systems[0] and "mid-fight" in systems[1]
