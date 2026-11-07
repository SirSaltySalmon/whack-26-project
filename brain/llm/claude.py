"""Claude client, used for reporting on screenshots. Implements VisionLLM."""

import logging
from base64 import standard_b64encode
from typing import Any

import anthropic

from brain.llm.base import (
    Detail,
    LLMEmptyResponseError,
    LLMUnavailableError,
    RateLimiter,
    SchemaT,
)

log = logging.getLogger(__name__)


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
    def __init__(self, model: str, api_key: str, limiter: RateLimiter) -> None:
        self._model = model
        # No retries: a retried frame arrives too late to describe what's on screen now.
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0, timeout=10.0)
        self._limiter = limiter

    async def vision_json(
        self,
        prompt: str,
        image: bytes,
        media_type: str,
        schema: type[SchemaT],
        max_tokens: int,
        detail: Detail = "low",  # Claude reads the image at the size it's sent, so this is unused.
    ) -> SchemaT:
        if not self._limiter.try_acquire():
            raise LLMUnavailableError(f"Local rate limit reached for {self._model}")
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
        except anthropic.AuthenticationError as exc:
            raise LLMUnavailableError(f"Anthropic rejected the API key: {exc.message}") from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMUnavailableError(f"Anthropic refused access: {exc.message}") from exc
        except anthropic.RateLimitError as exc:
            log.warning("Anthropic rate limit hit for %s: %s", self._model, exc.message)
            raise LLMUnavailableError(f"Anthropic rate limit hit for {self._model}") from exc

        if message.stop_reason in ("refusal", "max_tokens"):
            raise LLMEmptyResponseError(f"{self._model} stopped early: {message.stop_reason}")
        text = next((block.text for block in message.content if block.type == "text"), None)
        if not text:
            raise LLMEmptyResponseError(f"{self._model} returned no text")
        return schema.model_validate_json(text)
