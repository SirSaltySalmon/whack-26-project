"""Claude client: screen reports, close looks and pointing (VisionLLM), talker replies and deep
reasoning (TextLLM), and player turns with tools (ToolLLM)."""

import logging
from base64 import standard_b64encode
from collections.abc import AsyncIterator, Sequence
from typing import Any, Literal

import anthropic
import httpx2  # The SDK's own HTTP library. anthropic is pinned exactly, so this is too.
from anthropic.types import TextBlockParam

from brain.llm.base import (
    ChatTurn,
    Detail,
    Limiter,
    LLMEmptyResponseError,
    LLMUnavailableError,
    SchemaT,
    System,
    ToolDeclaration,
)
from brain.llm.claude_tools import ClaudeToolChat, chat_messages
from brain.llm.usage import CallTimer, log_usage, stream_snapshot

log = logging.getLogger(__name__)

Effort = Literal["low", "medium", "high"]
# Thinking tokens count against max_tokens, so a thinking call adds this on top of the caller's
# cap, which is meant for the visible answer.
THINKING_HEADROOM_TOKENS = 4000
# On a policy decline the API reruns the request on a model it picks, inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# The SDK drops idle connections after 5 s, but the talker can go a minute between turns, and a
# new connection pays a TCP and TLS handshake before the first token. The server closing one
# first is fine: the pool notices and opens another.
KEEPALIVE_S = 120.0


def shared_http_client() -> httpx2.AsyncClient:
    """One pool for every Claude role, so the observer's steady calls keep it warm for turns."""
    return anthropic.DefaultAsyncHttpxClient(
        limits=httpx2.Limits(
            max_connections=100, max_keepalive_connections=20, keepalive_expiry=KEEPALIVE_S
        )
    )


# Anthropic's structured output rejects these with a 400. The reply is still validated against
# the full pydantic model, so dropping them here loosens nothing.
_UNSUPPORTED = frozenset(
    {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"}
    | {"minLength", "maxLength"}
)
# Their values map field names to schemas, so a field called "maximum" must survive.
_NAMED = frozenset({"properties", "$defs", "definitions"})


def strict_schema(schema: Any) -> Any:
    """Fits a pydantic JSON schema to what Anthropic's structured output accepts.

    Every object must forbid extra fields, and number and string limits aren't supported.
    """
    if isinstance(schema, list):
        return [strict_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    fixed: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _UNSUPPORTED:
            continue
        if key in _NAMED and isinstance(value, dict):
            fixed[key] = {name: strict_schema(sub) for name, sub in value.items()}
        else:
            fixed[key] = strict_schema(value)
    if fixed.get("type") == "object":
        fixed["additionalProperties"] = False
    return fixed


def system_param(system: System) -> str | list[TextBlockParam]:
    """A plain string goes as is. Parts go as text blocks, and a part marked cache gets a
    breakpoint: the API then caches the tools and system up to it. Haiku 5.5 and Sonnet 5.5 only
    cache prefixes of 512 tokens or more, so a shorter one, such as think_hard's instructions with
    no tools, isn't cached, with no error, and that's expected."""
    if isinstance(system, str):
        return system
    blocks: list[TextBlockParam] = []
    for part in system:
        if not part.text:
            continue
        block: TextBlockParam = {"type": "text", "text": part.text}
        if part.cache:
            block["cache_control"] = {"type": "ephemeral"}
        blocks.append(block)
    return blocks


class ClaudeClient:
    def __init__(
        self,
        model: str,
        api_key: str,
        limiter: Limiter,
        effort: Effort = "low",
        timeout_s: float = 10.0,
        think: bool = True,
        fallback: bool = True,
        http_client: httpx2.AsyncClient | None = None,
        role: str = "claude",
        tools_role: str | None = None,
    ) -> None:
        """`role` labels this client's usage lines, and `tools_role` its tool turns, which for
        the talker's client are player turns rather than event reactions."""
        self._role = role
        self._tools_role = tools_role or role
        self._model = model
        # No retries: a retried frame arrives too late to describe what's on screen now, and a
        # retried deep answer too late for the turn that asked.
        # The timeout is applied per request, so roles sharing http_client keep their own.
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, max_retries=0, timeout=timeout_s, http_client=http_client
        )
        self._limiter = limiter
        self._effort = effort
        # Off for the talker: thinking costs time on the voice path.
        self._think = think
        # Server-side fallback on a refusal. Haiku has none, so its clients turn it off.
        self._fallback = fallback

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

    def _reasoning(self, max_tokens: int) -> dict[str, Any]:
        """Thinking keeps the model's reasoning out of its reply, as the API documents: with it
        off, a tip once opened by describing the player's screen. Off is faster."""
        if not self._think:
            return {
                "max_tokens": max_tokens,
                "thinking": {"type": "disabled"},
                "output_config": {"effort": "low"},
            }
        return {
            "max_tokens": max_tokens + THINKING_HEADROOM_TOKENS,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self._effort},
        }

    async def stream_text(
        self, system: System, prompt: str, max_tokens: int, history: Sequence[ChatTurn] = ()
    ) -> AsyncIterator[str]:
        """With thinking on, effort sets how much; with it off, this is a fast plain reply."""
        self._acquire()
        params: dict[str, Any] = {
            "model": self._model,
            "system": system_param(system),
            "messages": chat_messages(history, prompt),
            **self._reasoning(max_tokens),
        }
        timer = CallTimer()
        try:
            if self._think and self._fallback:
                stream = self._client.beta.messages.stream(
                    **params, betas=[FALLBACK_BETA], fallbacks="default"
                )
            else:
                stream = self._client.messages.stream(**params)
            async with stream as replies:
                try:
                    async for text in replies.text_stream:
                        timer.first_token()
                        yield text
                finally:
                    # Also when the caller stops reading early, as the talker does past its word
                    # cap: the snapshot then holds what was used so far.
                    log_usage(self._role, self._model, timer, stream_snapshot(replies))
                message = await replies.get_final_message()
        except anthropic.APIStatusError as exc:
            unavailable = self._unavailable(exc)
            if unavailable is None:
                raise
            raise unavailable from exc
        if message.stop_reason in ("refusal", "max_tokens"):
            log.warning("%s stopped early: %s", self._model, message.stop_reason)

    def tool_chat(
        self,
        system: System,
        tools: Sequence[ToolDeclaration],
        max_tokens: int,
        history: Sequence[ChatTurn] = (),
    ) -> ClaudeToolChat:
        return ClaudeToolChat(self, system, tools, max_tokens, history)

    async def create_with_tools(
        self,
        messages: list[dict[str, Any]],
        system: System,
        tools: list[dict[str, Any]],
        max_tokens: int,
        allow_tools: bool,
    ) -> Any:
        """Tools run in our own loop, so the director can cancel them and every call is logged."""
        self._acquire()
        timer = CallTimer()
        try:
            # Thinking blocks come back in message.content, which the tool chat replays as is.
            message = await self._client.messages.create(
                model=self._model,
                system=system_param(system),
                **self._reasoning(max_tokens),
                tools=tools,
                tool_choice={"type": "auto"} if allow_tools else {"type": "none"},
                messages=messages,
            )
        except anthropic.APIStatusError as exc:
            unavailable = self._unavailable(exc)
            if unavailable is None:
                raise
            raise unavailable from exc
        log_usage(self._tools_role, self._model, timer, message)
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
        timer = CallTimer()
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
        log_usage(self._role, self._model, timer, message)

        if message.stop_reason in ("refusal", "max_tokens"):
            raise LLMEmptyResponseError(f"{self._model} stopped early: {message.stop_reason}")
        text = next((block.text for block in message.content if block.type == "text"), None)
        if not text:
            raise LLMEmptyResponseError(f"{self._model} returned no text")
        return schema.model_validate_json(text)
