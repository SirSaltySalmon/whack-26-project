"""ClaudeToolChat: tool calls out, results back in one message, tools off on request."""

from types import SimpleNamespace
from typing import Any

import pytest

from brain.llm.base import LLMEmptyResponseError, RateLimiter, ToolDeclaration
from brain.llm.claude import ClaudeClient

TOOLS = [ToolDeclaration("wiki", "Look something up.", {"type": "object", "properties": {}})]


class ScriptedMessages:
    def __init__(self, *replies: SimpleNamespace) -> None:
        self._replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        # Copied, because the chat keeps appending to the same list.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self._replies.pop(0)


def reply(*blocks: SimpleNamespace, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason)


def text(value: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=value)


def tool_use(name: str, call_id: str, args: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, id=call_id, input=args)


def chat_with(messages: ScriptedMessages):  # type: ignore[no-untyped-def]
    built = ClaudeClient("test-model", "test-key", RateLimiter(10), think=False)
    built._client = SimpleNamespace(messages=messages)  # type: ignore[assignment]
    return built.tool_chat("Be brief.", TOOLS, 200)


async def test_a_tool_call_then_its_result_then_words() -> None:
    messages = ScriptedMessages(
        reply(tool_use("wiki", "t1", {"q": "slime"}), stop_reason="tool_use"),
        reply(text("Slimes are weak.")),
    )
    chat = chat_with(messages)
    step = await chat.send("what's a slime")
    assert step.calls[0].name == "wiki" and step.calls[0].args == {"q": "slime"}
    assert messages.calls[0]["tool_choice"] == {"type": "auto"}
    assert messages.calls[0]["tools"][0]["input_schema"] == {"type": "object", "properties": {}}

    step = await chat.send_results([(step.calls[0], "A weak enemy.")], allow_tools=False)
    assert step.text == "Slimes are weak." and not step.calls
    sent = messages.calls[1]
    assert sent["tool_choice"] == {"type": "none"}
    assert sent["messages"][-1]["content"] == [
        {"type": "tool_result", "tool_use_id": "t1", "content": "A weak enemy."}
    ]
    assert sent["messages"][1]["role"] == "assistant"


async def test_empty_content_is_an_error() -> None:
    with pytest.raises(LLMEmptyResponseError):
        await chat_with(ScriptedMessages(reply())).send("hi")


async def test_a_refusal_is_an_error() -> None:
    with pytest.raises(LLMEmptyResponseError):
        await chat_with(ScriptedMessages(reply(text("no"), stop_reason="refusal"))).send("hi")
