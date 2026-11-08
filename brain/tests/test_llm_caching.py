"""System prompts in parts, cache breakpoints on the wire, and one usage line per Claude call."""

import logging
from collections.abc import AsyncGenerator, Sequence
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import BaseModel

from brain.llm.base import RateLimiter, SystemPart, ToolDeclaration, system_text
from brain.llm.claude import ClaudeClient, system_param
from brain.llm.usage import CallTimer
from brain.tests.fake_gemini import gemini

PARTS = (SystemPart("Rules.", cache=True), SystemPart("NOW: danger: none"))
# The API gives None for a cache field with nothing in it.
USAGE = SimpleNamespace(
    input_tokens=120,
    cache_read_input_tokens=2400,
    cache_creation_input_tokens=None,
    output_tokens=18,
)
TOOLS = [ToolDeclaration("wiki", "Look something up.", {"type": "object", "properties": {}})]


class Answer(BaseModel):
    value: str


def test_parts_join_with_blank_lines_and_a_plain_string_passes_through() -> None:
    assert system_text(PARTS) == "Rules.\n\nNOW: danger: none"
    assert system_text((SystemPart("Rules.", cache=True), SystemPart(""))) == "Rules."
    assert system_text("Be brief.") == "Be brief."


def test_only_the_cached_part_gets_a_breakpoint_and_empty_parts_are_left_out() -> None:
    assert system_param("Be brief.") == "Be brief."
    assert system_param((*PARTS, SystemPart(""))) == [
        {"type": "text", "text": "Rules.", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "NOW: danger: none"},
    ]


class FakeStream:
    def __init__(self, chunks: list[str], usage: object | None) -> None:
        self._chunks = chunks
        self._usage = usage

    async def __aenter__(self) -> "FakeStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    @property
    async def text_stream(self):  # type: ignore[no-untyped-def]
        for chunk in self._chunks:
            yield chunk

    @property
    def current_message_snapshot(self) -> SimpleNamespace:
        if self._usage is None:
            raise AssertionError("No events yet")  # As the SDK does before the first event
        return SimpleNamespace(usage=self._usage)

    async def get_final_message(self) -> SimpleNamespace:
        return SimpleNamespace(stop_reason="end_turn", usage=self._usage)


class FakeMessages:
    def __init__(
        self, chunks: Sequence[str] = (), usage: object | None = USAGE, text: str = "Hi."
    ) -> None:
        self.chunks = list(chunks)
        self.usage = usage
        self.text = text
        self.kwargs: dict[str, Any] = {}

    def stream(self, **kwargs: Any) -> FakeStream:
        self.kwargs = kwargs
        return FakeStream(self.chunks, self.usage)

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.kwargs = kwargs
        content = [SimpleNamespace(type="text", text=self.text)]
        return SimpleNamespace(content=content, stop_reason="end_turn", usage=self.usage)


def claude(messages: FakeMessages, **kwargs: Any) -> ClaudeClient:
    built = ClaudeClient(
        "claude-test", "key", RateLimiter(10), think=False, fallback=False, **kwargs
    )
    built._client = SimpleNamespace(messages=messages)  # type: ignore[assignment]
    return built


def usage_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("LLM usage:")]


async def test_a_streamed_reply_sends_the_parts_and_logs_its_usage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="brain.llm.usage")
    messages = FakeMessages(["Try ", "a torch."])
    built = claude(messages, role="talker")
    chunks = [chunk async for chunk in built.stream_text(PARTS, "Now?", 100)]
    assert "".join(chunks) == "Try a torch."
    assert messages.kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    [line] = usage_lines(caplog)
    assert line.startswith("LLM usage: role=talker model=claude-test ttft_ms=")
    assert line.endswith("input=120 cache_read=2400 cache_write=0 output=18")


async def test_a_reply_the_caller_stops_reading_still_logs_its_usage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The talker stops reading past its word cap, so the line must come from what arrived so far.
    caplog.set_level(logging.INFO, logger="brain.llm.usage")
    built = claude(FakeMessages(["One. ", "Two. ", "Three."]))
    # stream_text is typed as an iterator, but it's a generator, which is what lets it be closed.
    stream = cast(AsyncGenerator[str, None], built.stream_text(PARTS, "Hi", 100))
    assert await anext(stream) == "One. "
    await stream.aclose()
    [line] = usage_lines(caplog)
    assert "cache_read=2400" in line


async def test_a_stream_with_no_usage_logs_zeros(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="brain.llm.usage")
    _ = [chunk async for chunk in claude(FakeMessages(["Hi."], usage=None)).stream_text("T", "", 9)]
    [line] = usage_lines(caplog)
    assert line.endswith("input=0 cache_read=0 cache_write=0 output=0")


async def test_tool_turns_send_the_parts_and_log_under_the_tools_role(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="brain.llm.usage")
    messages = FakeMessages()
    built = claude(messages, role="talker", tools_role="agent")
    step = await built.tool_chat(PARTS, TOOLS, 200).send("what's that?")
    assert step.text == "Hi."
    assert messages.kwargs["system"] == system_param(PARTS)
    [line] = usage_lines(caplog)
    assert line.startswith("LLM usage: role=agent ") and "cache_read=2400" in line


async def test_vision_logs_under_its_role(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="brain.llm.usage")
    built = claude(FakeMessages(text='{"value": "seen"}'), role="observer")
    assert (await built.vision_json("Look.", b"img", "image/jpeg", Answer, 50)).value == "seen"
    [line] = usage_lines(caplog)
    assert line.startswith("LLM usage: role=observer ")


def test_time_to_first_token_stops_at_the_first_text_or_else_at_the_end() -> None:
    times = iter([1.0, 1.25, 9.0])
    timer = CallTimer(clock=lambda: next(times))
    timer.first_token()
    timer.first_token()  # Only the first counts
    assert timer.ttft_ms() == 250
    whole = iter([2.0, 2.5])
    assert CallTimer(clock=lambda: next(whole)).ttft_ms() == 500


async def test_gemini_joins_the_parts_into_one_instruction() -> None:
    client, models = gemini(["Hi."])
    _ = [chunk async for chunk in client.stream_text(PARTS, "hello", 64)]
    assert models.calls[0].config.system_instruction == "Rules.\n\nNOW: danger: none"
    assert client.tool_chat(PARTS, TOOLS, 64)._system == "Rules.\n\nNOW: danger: none"
