import pytest
from pydantic import SecretStr

from brain.config import Settings
from brain.llm.base import LLMUnavailableError, RateLimiter
from brain.llm.claude import ClaudeClient
from brain.llm.factory import LLMFactory

# GeminiClient's own behaviour is in test_gemini_client.py and test_gemini_tool_chat.py.


def test_limiter_refuses_over_the_limit_then_recovers() -> None:
    now = 0.0
    limiter = RateLimiter(2, clock=lambda: now)
    assert limiter.try_acquire() and limiter.try_acquire()
    assert not limiter.try_acquire()
    now = 60.0
    assert limiter.try_acquire()


def test_missing_key_is_a_clear_error() -> None:
    factory = LLMFactory(Settings(_env_file=None, anthropic_api_key=None))  # type: ignore[call-arg]
    with pytest.raises(LLMUnavailableError, match="ANTHROPIC_API_KEY"):
        factory.talker()


def test_a_gemini_model_name_still_builds_a_gemini_client() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, gemini_api_key=SecretStr("test"), talker_model="gemini-test"
    )
    with pytest.raises(LLMUnavailableError, match="GEMINI_API_KEY"):
        LLMFactory(Settings(_env_file=None, talker_model="gemini-test")).talker()  # type: ignore[call-arg]
    assert not isinstance(LLMFactory(settings).talker(), ClaudeClient)


def test_talker_and_vision_run_on_claude_without_thinking_by_default() -> None:
    settings = Settings(_env_file=None, anthropic_api_key=SecretStr("test"))  # type: ignore[call-arg]
    factory = LLMFactory(settings)
    talker, vision = factory.talker(), factory.vision()
    assert isinstance(talker, ClaudeClient) and isinstance(vision, ClaudeClient)
    assert talker._model == "claude-haiku-5-5" and not talker._think


def test_roles_on_the_same_model_share_one_quota() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        gemini_api_key=SecretStr("test"),
        vision_model="same",
        # Without ANTHROPIC_API_KEY, deep runs on its Gemini fallback.
        deep_fallback_model="same",
        rpm_by_model={"same": 1},
    )
    factory = LLMFactory(settings)
    vision, deep = factory.vision(), factory.deep()
    assert vision._limiter is deep._limiter
    assert vision._limiter.try_acquire()
    assert not deep._limiter.try_acquire()


def test_deep_uses_claude_at_the_configured_effort_when_its_key_is_set() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        anthropic_api_key=SecretStr("test"),
        deep_model="claude-test",
        deep_effort="low",
    )
    deep = LLMFactory(settings).deep()
    assert isinstance(deep, ClaudeClient)
    assert deep._model == "claude-test" and deep._effort == "low" and deep._fallback


def test_tips_think_briefly_on_the_talker_model_without_a_fallback() -> None:
    settings = Settings(_env_file=None, anthropic_api_key=SecretStr("test"))  # type: ignore[call-arg]
    tips = LLMFactory(settings).tips()
    assert isinstance(tips, ClaudeClient)
    assert tips._model == "claude-haiku-5-5" and tips._think and tips._effort == "low"
    # Haiku has no server-side fallback, so asking for one would fail every tip.
    assert not tips._fallback


def test_talker_thinking_turns_it_on_for_replies_and_player_turns() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, anthropic_api_key=SecretStr("test"), talker_thinking=True
    )
    talker = LLMFactory(settings).talker()
    assert isinstance(talker, ClaudeClient) and talker._think and not talker._fallback
