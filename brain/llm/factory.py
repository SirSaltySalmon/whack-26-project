"""Builds the client for each role, so changing a model or vendor happens in one place."""

from google.genai import types

from brain.config import Settings
from brain.llm.base import LLMUnavailableError, RateLimiter
from brain.llm.claude import ClaudeClient
from brain.llm.gemini import GeminiClient

DEFAULT_RPM = 5


class LLMFactory:
    """Shares one limiter per model, because quota is per model and vision and deep can overlap."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._limiters: dict[str, RateLimiter] = {}

    def _limiter(self, model: str) -> RateLimiter:
        if model not in self._limiters:
            rpm = self._settings.rpm_by_model.get(model, DEFAULT_RPM)
            self._limiters[model] = RateLimiter(rpm)
        return self._limiters[model]

    def _build(self, model: str, thinking: types.ThinkingLevel) -> GeminiClient:
        key = self._settings.gemini_api_key
        if key is None:
            raise LLMUnavailableError("GEMINI_API_KEY isn't set")
        return GeminiClient(model, key.get_secret_value(), self._limiter(model), thinking)

    def talker(self) -> GeminiClient:
        # Thinking costs time on the voice path.
        return self._build(self._settings.talker_model, types.ThinkingLevel.MINIMAL)

    def vision(self) -> GeminiClient:
        return self._build(self._settings.vision_model, types.ThinkingLevel.LOW)

    def observer(self) -> ClaudeClient:
        model = self._settings.observer_model
        key = self._settings.anthropic_api_key
        if key is None:
            raise LLMUnavailableError("ANTHROPIC_API_KEY isn't set")
        return ClaudeClient(model, key.get_secret_value(), self._limiter(model))

    def deep(self) -> GeminiClient:
        return self._build(self._settings.deep_model, types.ThinkingLevel.HIGH)
