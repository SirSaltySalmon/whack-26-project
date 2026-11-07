import pytest
from pydantic import SecretStr

from brain.config import Settings
from brain.llm.base import LLMUnavailableError, RateLimiter
from brain.llm.factory import LLMFactory


def test_limiter_refuses_over_the_limit_then_recovers() -> None:
    now = 0.0
    limiter = RateLimiter(2, clock=lambda: now)
    assert limiter.try_acquire() and limiter.try_acquire()
    assert not limiter.try_acquire()
    now = 60.0
    assert limiter.try_acquire()


def test_missing_key_is_a_clear_error() -> None:
    factory = LLMFactory(Settings(_env_file=None, gemini_api_key=None))  # type: ignore[call-arg]
    with pytest.raises(LLMUnavailableError, match="GEMINI_API_KEY"):
        factory.talker()


def test_roles_on_the_same_model_share_one_quota() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        gemini_api_key=SecretStr("test"),
        vision_model="same",
        deep_model="same",
        rpm_by_model={"same": 1},
    )
    factory = LLMFactory(settings)
    vision, deep = factory.vision(), factory.deep()
    assert vision._limiter is deep._limiter
    assert vision._limiter.try_acquire()
    assert not deep._limiter.try_acquire()
