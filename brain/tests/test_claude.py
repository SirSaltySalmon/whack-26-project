from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from brain.llm.base import LLMEmptyResponseError, LLMUnavailableError, RateLimiter
from brain.llm.claude import ClaudeClient, strict_schema


class Answer(BaseModel):
    value: str


class FakeMessages:
    def __init__(self, text: str | None, stop_reason: str = "end_turn") -> None:
        self.text = text
        self.stop_reason = stop_reason
        self.kwargs: dict[str, object] = {}

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.kwargs = kwargs
        content = [] if self.text is None else [SimpleNamespace(type="text", text=self.text)]
        return SimpleNamespace(content=content, stop_reason=self.stop_reason)


def client(messages: FakeMessages, limit: int = 5) -> ClaudeClient:
    built = ClaudeClient("test-model", "test-key", RateLimiter(limit))
    built._client = SimpleNamespace(messages=messages)  # type: ignore[assignment]
    return built


async def ask(built: ClaudeClient) -> Answer:
    return await built.vision_json("Look.", b"image", "image/jpeg", Answer, 100)


async def test_returns_the_parsed_schema_and_asks_for_structured_output() -> None:
    messages = FakeMessages('{"value": "seen"}')
    assert (await ask(client(messages))).value == "seen"
    assert messages.kwargs["model"] == "test-model"
    assert messages.kwargs["system"] == "Look."
    assert messages.kwargs["output_config"]["format"]["type"] == "json_schema"  # type: ignore[index]


async def test_refuses_over_the_local_limit_without_calling_out() -> None:
    messages = FakeMessages('{"value": "seen"}')
    with pytest.raises(LLMUnavailableError):
        await ask(client(messages, limit=0))
    assert messages.kwargs == {}


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
async def test_incomplete_replies_are_errors(stop_reason: str) -> None:
    with pytest.raises(LLMEmptyResponseError):
        await ask(client(FakeMessages('{"value": "s', stop_reason)))


async def test_no_text_is_an_error() -> None:
    with pytest.raises(LLMEmptyResponseError):
        await ask(client(FakeMessages(None)))


class Inner(BaseModel):
    name: str


class Outer(BaseModel):
    inner: Inner
    items: list[Inner]


def test_every_object_forbids_extra_fields_as_anthropic_requires() -> None:
    schema = strict_schema(Outer.model_json_schema())
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["Inner"]["additionalProperties"] is False


async def test_the_schema_sent_is_strict() -> None:
    messages = FakeMessages('{"value": "seen"}')
    await ask(client(messages))
    sent = messages.kwargs["output_config"]["format"]["schema"]  # type: ignore[index]
    assert sent["additionalProperties"] is False


class FakeStream:
    def __init__(self, chunks: list[str], stop_reason: str) -> None:
        self._chunks = chunks
        self._stop_reason = stop_reason

    async def __aenter__(self) -> "FakeStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    @property
    async def text_stream(self):  # type: ignore[no-untyped-def]
        for chunk in self._chunks:
            yield chunk

    async def get_final_message(self) -> SimpleNamespace:
        return SimpleNamespace(stop_reason=self._stop_reason)


class FakeBetaMessages:
    def __init__(self, chunks: list[str], stop_reason: str = "end_turn") -> None:
        self.chunks = chunks
        self.stop_reason = stop_reason
        self.kwargs: dict[str, object] = {}

    def stream(self, **kwargs: object) -> FakeStream:
        self.kwargs = kwargs
        return FakeStream(self.chunks, self.stop_reason)


def text_client(messages: FakeBetaMessages, limit: int = 5) -> ClaudeClient:
    built = ClaudeClient("test-model", "test-key", RateLimiter(limit), effort="medium")
    built._client = SimpleNamespace(beta=SimpleNamespace(messages=messages))  # type: ignore[assignment]
    return built


async def test_streams_text_with_thinking_on_at_the_chosen_effort() -> None:
    messages = FakeBetaMessages(["Mine ", "hellstone."])
    chunks = [chunk async for chunk in text_client(messages).stream_text("Plan.", "Next?", 100)]
    assert "".join(chunks) == "Mine hellstone."
    assert messages.kwargs["thinking"] == {"type": "adaptive"}
    assert messages.kwargs["output_config"] == {"effort": "medium"}
    # The caller's cap is for the visible answer; thinking gets room on top.
    assert messages.kwargs["max_tokens"] > 100


async def test_streaming_refuses_over_the_local_limit() -> None:
    messages = FakeBetaMessages(["x"])
    built = text_client(messages, limit=0)
    with pytest.raises(LLMUnavailableError):
        _ = [chunk async for chunk in built.stream_text("Plan.", "Next?", 100)]
    assert messages.kwargs == {}
