"""Claude client: screen reports, close looks and pointing (VisionLLM), talker replies and deep
reasoning (TextLLM), and player turns with tools (ToolLLM)."""

import logging
from base64 import standard_b64encode
from collections.abc import AsyncIterator, Sequence
from typing import Any, Literal

import anthropic

from brain.llm.base import (
    Detail,
    LLMEmptyResponseError,
    LLMUnavailableError,
    RateLimiter,
    SchemaT,
    ToolDeclaration,
)
from brain.llm.claude_tools import ClaudeToolChat

log = logging.getLogger(__name__)

Effort = Literal["low", "medium", "high"]
# Thinking tokens count against max_tokens, so stream_text adds this on top of the caller's cap,
# which is meant for the visible answer.
THINKING_HEADROOM_TOKENS = 4000
# On a policy decline the API reruns the request on a model it picks, inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def strict_schema(schema: Any) -> Any:
    """Anthropic's structured output rejects any object that doesn't forbid extra fields."""
    if isinstance(schema, dict):
        fixed = {key: strict_schema(value) for key, value in schema.items()}
        if fixed.get("type") == "object":
            fixed["additionalProperties"] = False
        return fixed
    if isinstance(schema, list):
        return [strict_schema(item) for item in schema]
    return schema


class ClaudeClient:
    def __init__(
        self,
        model: str,
        api_key: str,
        limiter: RateLimiter,
        effort: Effort = "low",
        timeout_s: float = 10.0,
        think: bool = True,
    ) -> None:
        self._model = model
        # No retries: a retried frame arrives too late to describe what's on screen now, and a
        # retried deep answer too late for the turn that asked.
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0, timeout=timeout_s)
        self._limiter = limiter
        self._effort = effort
        # Off for the talker: thinking costs time on the voice path.
        self._think = think

    def _acquire(self) -> None:
        if not self._limiter.try_acquire():
            raise LLMUnavailableError(f"Local rate limit reached for {self._model}")

    def _unavailable(self, exc: anthropic.APIStatusError) -> LLMUnavailableError | None:
        if isinstance(exc, anthropic.AuthenticationError):
            return LLMUnavailableError(f"Anthropic rejected the API key: {exc.message}")
        if isinstance(exc, anthropic.PermissionDeniedError):
            return LLMUnavailableError(f"Anthropic refused access: {exc.message}")
        if isinstance(exc, anthropic.RateLimitError):
            log.warning("Anthropic rate limit hit for %s: %s", self._model, exc.message)
            return LLMUnavailableError(f"Anthropic rate limit hit for {self._model}")
        return None

    async def stream_text(self, system: str, prompt: str, max_tokens: int) -> AsyncIterator[str]:
        """With thinking on, effort sets how much; with it off, this is a fast plain reply."""
        if not self._think:
            async for text in self._stream_fast(system, prompt, max_tokens):
                yield text
            return
        self._acquire()
        try:
            async with self._client.beta.messages.stream(
                model=self._model,
                max_tokens=max_tokens + THINKING_HEADROOM_TOKENS,
                system=system,
                thinking={"type": "adaptive"},
                output_config={"effort": self._effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                async for text in stream.text_stream:
                    yield text
                message = await stream.get_final_message()
        except anthropic.APIStatusError as exc:
            unavailable = self._unavailable(exc)
            if unavailable is None:
                raise
            raise unavailable from exc
        if message.stop_reason in ("refusal", "max_tokens"):
            log.warning("%s stopped early: %s", self._model, message.stop_reason)

    async def _stream_fast(self, system: str, prompt: str, max_tokens: int) -> AsyncIterator[str]:
        # No server-side fallback: Haiku has none, and the talker would rather stay quiet.
        self._acquire()
        try:
            async with self._client.messages.stream(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                thinking={"type": "disabled"},
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                async for text in stream.text_stream:
                    yield text
                message = await stream.get_final_message()
        except anthropic.APIStatusError as exc:
            unavailable = self._unavailable(exc)
            if unavailable is None:
                raise
            raise unavailable from exc
        if message.stop_reason in ("refusal", "max_tokens"):
            log.warning("%s stopped early: %s", self._model, message.stop_reason)

    def tool_chat(
        self, system: str, tools: Sequence[ToolDeclaration], max_tokens: int
    ) -> ClaudeToolChat:
        return ClaudeToolChat(self, system, tools, max_tokens)

    async def create_with_tools(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]],
        max_tokens: int,
        allow_tools: bool,
    ) -> Any:
        """Tools run in our own loop, so the director can cancel them and every call is logged."""
        self._acquire()
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                thinking={"type": "disabled"},
                output_config={"effort": "low"},
                tools=tools,
                tool_choice={"type": "auto"} if allow_tools else {"type": "none"},
                messages=messages,
            )
        except anthropic.APIStatusError as exc:
            unavailable = self._unavailable(exc)
            if unavailable is None:
                raise
            raise unavailable from exc
        if message.stop_reason == "refusal":
            raise LLMEmptyResponseError(f"{self._model} refused a tool turn")
        return message

    async def vision_json(
        self,
        prompt: str,
        image: bytes,
        media_type: str,
        schema: type[SchemaT],
        max_tokens: int,
        detail: Detail = "low",  # Claude reads the image at the size it's sent, so this is unused.
    ) -> SchemaT:
        self._acquire()
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=prompt,
                # Reading a screen is simple, and thinking would double the reply time.
                thinking={"type": "disabled"},
                output_config={
                    "effort": "low",
                    "format": {
                        "type": "json_schema",
                        "schema": strict_schema(schema.model_json_schema()),
                    },
                },
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": standard_b64encode(image).decode("ascii"),
                                },
                            },
                            {"type": "text", "text": "Report on this frame."},
                        ],
                    }
                ],
            )
        except anthropic.APIStatusError as exc:
            unavailable = self._unavailable(exc)
            if unavailable is None:
                raise
            raise unavailable from exc

        if message.stop_reason in ("refusal", "max_tokens"):
            raise LLMEmptyResponseError(f"{self._model} stopped early: {message.stop_reason}")
        text = next((block.text for block in message.content if block.type == "text"), None)
        if not text:
            raise LLMEmptyResponseError(f"{self._model} returned no text")
        return schema.model_validate_json(text)
