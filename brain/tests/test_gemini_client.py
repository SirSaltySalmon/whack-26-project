"""GeminiClient's plain calls: streaming text and vision, and their limits and failures."""

from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import types
from pydantic import BaseModel

from brain.llm.base import Detail, LLMEmptyResponseError, LLMUnavailableError
from brain.tests.fake_gemini import api_error, gemini


class Answer(BaseModel):
    answer: str


async def test_a_quota_error_on_vision_counts_as_unavailable() -> None:
    client, _ = gemini(api_error(429))
    with pytest.raises(LLMUnavailableError):
        await client.vision_json("Look.", b"image", "image/jpeg", Answer, 100)


async def test_a_quota_error_while_streaming_counts_as_unavailable() -> None:
    client, _ = gemini(["Hello ", api_error(429)])
    with pytest.raises(LLMUnavailableError):
        async for _chunk in client.stream_text("Be brief.", "hello", 64):
            pass


async def test_the_limiter_refuses_vision_without_calling_the_model() -> None:
    client, models = gemini(rpm=0)
    with pytest.raises(LLMUnavailableError, match="rate limit"):
        await client.vision_json("Look.", b"image", "image/jpeg", Answer, 100)
    assert models.calls == []


async def test_the_limiter_refuses_streaming_without_calling_the_model() -> None:
    client, models = gemini(rpm=0)
    with pytest.raises(LLMUnavailableError, match="rate limit"):
        async for _chunk in client.stream_text("Be brief.", "hello", 64):
            pass
    assert models.calls == []


async def test_streaming_yields_the_text_and_skips_empty_chunks() -> None:
    client, models = gemini(["Hello ", "", None, "there."])
    parts = [chunk async for chunk in client.stream_text("Be brief.", "hello", 64)]
    assert parts == ["Hello ", "there."]
    assert models.calls[0].config.system_instruction == "Be brief."
    assert models.calls[0].config.max_output_tokens == 64


@pytest.mark.parametrize(
    ("detail", "level"),
    [
        ("low", types.PartMediaResolutionLevel.MEDIA_RESOLUTION_LOW),
        ("high", types.PartMediaResolutionLevel.MEDIA_RESOLUTION_HIGH),
    ],
)
async def test_vision_sets_the_resolution_per_image(detail: Detail, level: Any) -> None:
    client, models = gemini(SimpleNamespace(parsed=Answer(answer="A door."), text=None))
    await client.vision_json("Look.", b"image", "image/jpeg", Answer, 100, detail=detail)
    image, prompt = models.calls[0].contents
    assert image.media_resolution.level == level
    assert image.inline_data.data == b"image" and image.inline_data.mime_type == "image/jpeg"
    assert prompt.text == "Look."


async def test_vision_defaults_to_low_detail() -> None:
    client, models = gemini(SimpleNamespace(parsed=Answer(answer="A door."), text=None))
    await client.vision_json("Look.", b"image", "image/jpeg", Answer, 100)
    level = models.calls[0].contents[0].media_resolution.level
    assert level == types.PartMediaResolutionLevel.MEDIA_RESOLUTION_LOW


async def test_vision_uses_the_parsed_reply_or_parses_the_text_itself() -> None:
    parsed, _ = gemini(SimpleNamespace(parsed=Answer(answer="Parsed."), text=None))
    reply = await parsed.vision_json("Look.", b"image", "image/jpeg", Answer, 100)
    assert reply == Answer(answer="Parsed.")
    textual, _ = gemini(SimpleNamespace(parsed=None, text='{"answer": "From text."}'))
    reply = await textual.vision_json("Look.", b"image", "image/jpeg", Answer, 100)
    assert reply == Answer(answer="From text.")


async def test_vision_with_nothing_to_parse_is_an_empty_response_error() -> None:
    client, _ = gemini(SimpleNamespace(parsed=None, text=None))
    with pytest.raises(LLMEmptyResponseError):
        await client.vision_json("Look.", b"image", "image/jpeg", Answer, 100)
