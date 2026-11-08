"""Claude's side of player turns with tools (ToolChat), and the earlier conversation as messages.
Kept apart so claude.py stays short."""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from brain.llm.base import (
    ChatTurn,
    LLMEmptyResponseError,
    System,
    ToolCall,
    ToolDeclaration,
    ToolStep,
    merged_turns,
)

if TYPE_CHECKING:
    from brain.llm.claude import ClaudeClient


def history_messages(history: Sequence[ChatTurn]) -> list[dict[str, Any]]:
    """Earlier turns as plain text, with a cache breakpoint on the last one. The conversation
    only grows at its end, so the next call reads everything up to here from the cache and only
    its own latest message is new."""
    messages: list[dict[str, Any]] = [
        {"role": turn.role, "content": [{"type": "text", "text": turn.text}]}
        for turn in merged_turns(history)
    ]
    if messages:
        messages[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}
    return messages


def add_user(messages: list[dict[str, Any]], text: str) -> None:
    """Appends their message, joining the last one when that's theirs too, such as a line nobody
    answered, so turns still alternate."""
    if messages and messages[-1]["role"] == "user" and isinstance(messages[-1]["content"], list):
        messages[-1]["content"].append({"type": "text", "text": text})
    else:
        messages.append({"role": "user", "content": text})


def chat_messages(history: Sequence[ChatTurn], prompt: str) -> list[dict[str, Any]]:
    messages = history_messages(history)
    add_user(messages, prompt)
    return messages


class ClaudeToolChat:
    """Not streamed: a reply is collected before TTS anyway, and tool calls arrive whole."""

    def __init__(
        self,
        client: "ClaudeClient",
        system: System,
        tools: Sequence[ToolDeclaration],
        max_tokens: int,
        history: Sequence[ChatTurn] = (),
    ) -> None:
        self._client = client
        self._system = system
        self._tools = [
            {"name": tool.name, "description": tool.description, "input_schema": tool.parameters}
            for tool in tools
        ]
        self._max_tokens = max_tokens
        self._messages: list[dict[str, Any]] = history_messages(history)

    async def send(self, text: str) -> ToolStep:
        add_user(self._messages, text)
        return await self._generate(allow_tools=True)

    async def send_results(
        self, results: Sequence[tuple[ToolCall, str]], allow_tools: bool = True
    ) -> ToolStep:
        # All results go back in one message, or Claude learns to stop calling tools in parallel.
        content = [
            {"type": "tool_result", "tool_use_id": call.id, "content": output}
            for call, output in results
        ]
        self._messages.append({"role": "user", "content": content})
        return await self._generate(allow_tools)

    async def _generate(self, allow_tools: bool) -> ToolStep:
        message = await self._client.create_with_tools(
            self._messages, self._system, self._tools, self._max_tokens, allow_tools
        )
        if not message.content:
            raise LLMEmptyResponseError("Claude returned no content for a tool turn")
        # Sent back as received, so tool_use ids match their results on the next call.
        self._messages.append({"role": "assistant", "content": message.content})
        calls = tuple(
            ToolCall(name=block.name, args=dict(block.input or {}), id=block.id)
            for block in message.content
            if block.type == "tool_use"
        )
        text = "".join(block.text for block in message.content if block.type == "text")
        return ToolStep(text=text, calls=calls)
