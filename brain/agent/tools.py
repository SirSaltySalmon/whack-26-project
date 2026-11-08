"""The tools a player turn can use, in a form that doesn't depend on any LLM vendor or transport.

Each tool is a name, a description, a Pydantic input and an async handler, which is also the shape
an MCP server needs. Exposing these over MCP later only takes an adapter around this registry.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel, ValidationError

from brain.llm.base import (
    LLMEmptyResponseError,
    LLMUnavailableError,
    ToolCall,
    ToolDeclaration,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TurnContext:
    # When the player began speaking (monotonic), so "what's that?" looks at what they saw then.
    started_at: float | None = None


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    # Takes an instance of input_model. Returns text for the model, labelled as untrusted data.
    handler: Callable[[Any, TurnContext], Awaitable[str]]
    timeout_s: float = 10.0
    # Finishes at once, so it needs no "one sec" line and nothing to survive a barge-in for.
    quick: bool = False


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def declarations(self) -> list[ToolDeclaration]:
        return [
            ToolDeclaration(tool.name, tool.description, tool.input_model.model_json_schema())
            for tool in self._tools.values()
        ]

    def is_quick(self, call: ToolCall) -> bool:
        tool = self._tools.get(call.name)
        return tool is not None and tool.quick

    def including(self, *tools: Tool) -> "ToolRegistry":
        return ToolRegistry([*self._tools.values(), *tools])

    def only(self, *names: str) -> "ToolRegistry":
        """Just these tools, for a turn the player didn't start, which mustn't get the rest."""
        return ToolRegistry(tool for name, tool in self._tools.items() if name in names)

    def once(self) -> "ToolRegistry":
        """Each tool runs at most once, which bounds what an unasked-for turn can spend.

        Call it per turn: the count lives in the registry it returns.
        """
        return ToolRegistry(_once(tool) for tool in self._tools.values())

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    async def run(self, call: ToolCall, turn: TurnContext) -> str:
        """Always returns text. A failed tool is something the model can tell the player about."""
        tool = self._tools.get(call.name)
        if tool is None:
            log.warning("Model asked for an unknown tool: %s", call.name)
            return f"There's no tool called {call.name}."
        try:
            arguments = tool.input_model.model_validate(call.args)
        except ValidationError:
            log.warning("Invalid arguments for %s: %s", call.name, call.args, exc_info=True)
            return f"{call.name} was given invalid arguments."

        log.info("Tool %s: %s", call.name, call.args)
        try:
            return await asyncio.wait_for(tool.handler(arguments, turn), tool.timeout_s)
        except TimeoutError:
            log.warning("Tool %s timed out after %.0f s", call.name, tool.timeout_s)
            return f"{call.name} took too long and was stopped."
        except (LLMUnavailableError, LLMEmptyResponseError) as exc:
            log.warning("Tool %s unavailable: %s", call.name, exc)
            return f"{call.name} isn't available right now."
        except Exception:
            log.exception("Tool %s failed", call.name)
            return f"{call.name} failed."


def _once(tool: Tool) -> Tool:
    used = False

    async def handler(arguments: Any, turn: TurnContext) -> str:
        nonlocal used
        # Set before awaiting, so two calls in one model step can't both get through.
        if used:
            log.info("Tool %s already ran this turn; not running it again", tool.name)
            return f"{tool.name} already ran, so reply with what you have."
        used = True
        return await tool.handler(arguments, turn)

    return replace(tool, handler=handler)
