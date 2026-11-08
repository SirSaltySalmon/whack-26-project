"""Claude's side of player turns with tools (ToolChat), kept apart so claude.py stays short."""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from brain.llm.base import LLMEmptyResponseError, ToolCall, ToolDeclaration, ToolStep

if TYPE_CHECKING:
    from brain.llm.claude import ClaudeClient


class ClaudeToolChat:
    """Not streamed: a reply is collected before TTS anyway, and tool calls arrive whole."""

    def __init__(
        self,
        client: "ClaudeClient",
        system: str,
        tools: Sequence[ToolDeclaration],
        max_tokens: int,
    ) -> None:
        self._client = client
        self._system = system
        self._tools = [
            {"name": tool.name, "description": tool.description, "input_schema": tool.parameters}
            for tool in tools
        ]
        self._max_tokens = max_tokens
        self._messages: list[dict[str, Any]] = []

    async def send(self, text: str) -> ToolStep:
        self._messages.append({"role": "user", "content": text})
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
