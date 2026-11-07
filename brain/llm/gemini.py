"""Gemini client. Uses generate_content because it's stateless and available in the SDK version
Pipecat allows."""

import logging
from collections.abc import AsyncIterator

from google import genai
from google.genai import errors, types

from brain.llm.base import LLMEmptyResponseError, LLMUnavailableError, RateLimiter, SchemaT

log = logging.getLogger(__name__)

QUOTA_EXCEEDED = 429


class GeminiClient:
    def __init__(
        self,
        model: str,
        api_key: str,
        limiter: RateLimiter,
        thinking_level: types.ThinkingLevel = types.ThinkingLevel.LOW,
    ) -> None:
        self._model = model
        self._client = genai.Client(api_key=api_key)
        self._limiter = limiter
        self._thinking = types.ThinkingConfig(thinking_level=thinking_level)

    def _acquire(self) -> None:
        if not self._limiter.try_acquire():
            raise LLMUnavailableError(f"Local rate limit reached for {self._model}")

    def _quota_error(self, exc: errors.APIError) -> Exception:
        if exc.code == QUOTA_EXCEEDED:
            log.warning("Gemini quota exceeded for %s: %s", self._model, exc)
            return LLMUnavailableError(f"Gemini quota exceeded for {self._model}")
        return exc

    async def stream_text(self, system: str, prompt: str, max_tokens: int) -> AsyncIterator[str]:
        self._acquire()
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            thinking_config=self._thinking,
        )
        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=self._model, contents=prompt, config=config
            )
            async for chunk in stream:
                if chunk.text:
                    yield chunk.text
        except errors.APIError as exc:
            raise self._quota_error(exc) from exc

    async def vision_json(
        self,
        prompt: str,
        image: bytes,
        media_type: str,
        schema: type[SchemaT],
        max_tokens: int,
        resolution: types.PartMediaResolutionLevel = (
            types.PartMediaResolutionLevel.MEDIA_RESOLUTION_LOW
        ),
    ) -> SchemaT:
        self._acquire()
        contents = [
            types.Part.from_bytes(data=image, mime_type=media_type, media_resolution=resolution),
            types.Part.from_text(text=prompt),
        ]
        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
            response_schema=schema,
            thinking_config=self._thinking,
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model, contents=contents, config=config
            )
        except errors.APIError as exc:
            raise self._quota_error(exc) from exc

        if isinstance(response.parsed, schema):
            return response.parsed
        if response.text:
            return schema.model_validate_json(response.text)
        raise LLMEmptyResponseError(f"{self._model} returned no parsable output")
