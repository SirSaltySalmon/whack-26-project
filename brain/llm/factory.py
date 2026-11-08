"""Builds the client for each role, so changing a model or vendor happens in one place."""

import httpx2
from google.genai import types

from brain.config import Settings
from brain.llm.base import Limiter, LLMUnavailableError, RateLimiter, TextLLM, VisionLLM
from brain.llm.claude import ClaudeClient, shared_http_client
from brain.llm.gemini import GeminiClient

DEFAULT_RPM = 5


class LLMFactory:
    """Shares one limiter per model, because quota is per model and vision and deep can overlap."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._limiters: dict[str, RateLimiter] = {}
        # Made on first use and shared by every Claude role. See shared_http_client.
        self._http: httpx2.AsyncClient | None = None

    def _limiter(self, model: str, background: bool = False) -> Limiter:
        """`background` is for calls nobody is waiting on: they leave the player a share."""
        if model not in self._limiters:
            rpm = self._settings.rpm_by_model.get(model, DEFAULT_RPM)
            self._limiters[model] = RateLimiter(rpm)
        shared = self._limiters[model]
        return shared.for_background() if background else shared

    def _http_client(self) -> httpx2.AsyncClient:
        if self._http is None:
            self._http = shared_http_client()
        return self._http

    def _build(
        self, model: str, thinking: types.ThinkingLevel, background: bool = False
    ) -> GeminiClient:
        key = self._settings.gemini_api_key
        if key is None:
            raise LLMUnavailableError("GEMINI_API_KEY isn't set")
        return GeminiClient(
            model, key.get_secret_value(), self._limiter(model, background), thinking
        )

    def _fast(
        self,
        model: str,
        thinking: types.ThinkingLevel,
        role: str,
        think: bool = False,
        background: bool = False,
        tools_role: str | None = None,
    ) -> ClaudeClient | GeminiClient:
        """The vendor follows the model's name, so switching back is a config change. `role`
        labels the client's usage lines for scripts/latency_report.py."""
        if not model.startswith("claude"):
            return self._build(model, thinking, background)
        key = self._settings.anthropic_api_key
        if key is None:
            raise LLMUnavailableError("ANTHROPIC_API_KEY isn't set")
        limiter = self._limiter(model, background)
        # The fast roles run on Haiku, which has no server-side fallback.
        return ClaudeClient(
            model,
            key.get_secret_value(),
            limiter,
            think=think,
            fallback=False,
            http_client=self._http_client(),
            role=role,
            tools_role=tools_role,
        )

    def talker(self) -> ClaudeClient | GeminiClient:
        # Thinking costs time on the voice path, so it's off unless talker_thinking turns it on.
        think = self._settings.talker_thinking
        level = types.ThinkingLevel.LOW if think else types.ThinkingLevel.MINIMAL
        # The same client answers event reactions and runs player turns, which use tools.
        return self._fast(self._settings.talker_model, level, "talker", think, tools_role="agent")

    def tips(self) -> ClaudeClient | GeminiClient:
        """The talker's model, thinking briefly first. Nobody waits on a tip, and with thinking
        off a tip once opened by describing the player's screen."""
        return self._fast(
            self._settings.talker_model, types.ThinkingLevel.LOW, "tip", think=True, background=True
        )

    def vision(self, background: bool = False) -> ClaudeClient | GeminiClient:
        """Background for the learner and the progress scout; player-facing for pointing."""
        return self._fast(
            self._settings.vision_model, types.ThinkingLevel.LOW, "vision", background=background
        )

    def observer(self) -> ClaudeClient:
        model = self._settings.observer_model
        key = self._settings.anthropic_api_key
        if key is None:
            raise LLMUnavailableError("ANTHROPIC_API_KEY isn't set")
        # Background: it runs all the time, so it's what would otherwise crowd out a turn.
        return ClaudeClient(
            model,
            key.get_secret_value(),
            self._limiter(model, background=True),
            http_client=self._http_client(),
            role="observer",
        )

    def closeup(self) -> VisionLLM:
        """For questions about the screen while the player waits, so speed matters most."""
        key = self._settings.anthropic_api_key
        if key is None:
            return self.vision()
        model = self._settings.closeup_model
        return ClaudeClient(
            model,
            key.get_secret_value(),
            self._limiter(model),
            http_client=self._http_client(),
            role="closeup",
        )

    def deep(self, background: bool = False) -> TextLLM:
        """For think_hard and, in the background, session notes, the brief and naming the game.
        Falls back to Gemini without ANTHROPIC_API_KEY."""
        key = self._settings.anthropic_api_key
        if key is None:
            fallback = self._settings.deep_fallback_model
            return self._build(fallback, types.ThinkingLevel.HIGH, background)
        model = self._settings.deep_model
        return ClaudeClient(
            model,
            key.get_secret_value(),
            self._limiter(model, background),
            effort=self._settings.deep_effort,
            timeout_s=self._settings.deep_timeout_s,
            http_client=self._http_client(),
            role="deep",
        )
