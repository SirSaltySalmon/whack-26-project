"""Builds the client for each role, so changing a model or vendor happens in one place."""

from google.genai import types

from brain.config import Settings
from brain.llm.base import LLMUnavailableError, RateLimiter, TextLLM, VisionLLM
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

    def _fast(
        self, model: str, thinking: types.ThinkingLevel, think: bool = False
    ) -> ClaudeClient | GeminiClient:
        """The vendor follows the model's name, so switching back is a config change."""
        if not model.startswith("claude"):
            return self._build(model, thinking)
        key = self._settings.anthropic_api_key
        if key is None:
            raise LLMUnavailableError("ANTHROPIC_API_KEY isn't set")
        limiter = self._limiter(model)
        # The fast roles run on Haiku, which has no server-side fallback.
        return ClaudeClient(model, key.get_secret_value(), limiter, think=think, fallback=False)

    def talker(self) -> ClaudeClient | GeminiClient:
        # Thinking costs time on the voice path, so it's off unless talker_thinking turns it on.
        think = self._settings.talker_thinking
        level = types.ThinkingLevel.LOW if think else types.ThinkingLevel.MINIMAL
        return self._fast(self._settings.talker_model, level, think)

    def tips(self) -> ClaudeClient | GeminiClient:
        """The talker's model, thinking briefly first. Nobody waits on a tip, and with thinking
        off a tip once opened by describing the player's screen."""
        return self._fast(self._settings.talker_model, types.ThinkingLevel.LOW, think=True)

    def vision(self) -> ClaudeClient | GeminiClient:
        return self._fast(self._settings.vision_model, types.ThinkingLevel.LOW)

    def observer(self) -> ClaudeClient:
        model = self._settings.observer_model
        key = self._settings.anthropic_api_key
        if key is None:
            raise LLMUnavailableError("ANTHROPIC_API_KEY isn't set")
        return ClaudeClient(model, key.get_secret_value(), self._limiter(model))

    def closeup(self) -> VisionLLM:
        """For questions about the screen while the player waits, so speed matters most."""
        key = self._settings.anthropic_api_key
        if key is None:
            return self.vision()
        model = self._settings.closeup_model
        return ClaudeClient(model, key.get_secret_value(), self._limiter(model))

    def deep(self) -> TextLLM:
        """For think_hard and session notes. Falls back to Gemini without ANTHROPIC_API_KEY."""
        key = self._settings.anthropic_api_key
        if key is None:
            return self._build(self._settings.deep_fallback_model, types.ThinkingLevel.HIGH)
        model = self._settings.deep_model
        return ClaudeClient(
            model,
            key.get_secret_value(),
            self._limiter(model),
            effort=self._settings.deep_effort,
            timeout_s=self._settings.deep_timeout_s,
        )
