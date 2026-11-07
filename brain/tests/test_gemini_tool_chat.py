"""GeminiToolChat, which holds one player turn's conversation with the model."""

from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors, types

from brain.llm.base import LLMEmptyResponseError, LLMUnavailableError, ToolCall, ToolDeclaration
from brain.llm.gemini import GeminiClient, GeminiToolChat
from brain.tests.fake_gemini import api_error, gemini, model_turn

TOOLS = [
    ToolDeclaration(
        "look",
        "Look closer.",
        {"type": "object", "properties": {"question": {"type": "string"}}},
    )
]


def text_part(text: str) -> types.Part:
    return types.Part(text=text)


def call_part(
    name: str = "look", call_id: str = "call-1", signature: bytes | None = None
) -> types.Part:
    call = types.FunctionCall(id=call_id, name=name, args={"question": "what's that?"})
    return types.Part(function_call=call, thought_signature=signature)


def tool_chat(client: GeminiClient) -> GeminiToolChat:
    return client.tool_chat("Be brief.", TOOLS, 256)


async def test_tool_chat_sends_the_models_content_back_unchanged() -> None:
    # Gemini 3 rejects a follow-up whose thought signatures are gone, so it must be the same object.
    first = model_turn(call_part(signature=b"signature-1"))
    client, models = gemini(first, model_turn(text_part("Done.")))
    chat = tool_chat(client)
    step = await chat.send("what's that?")
    await chat.send_results([(step.calls[0], "A door.")])

    history = models.calls[1].contents
    assert [turn.role for turn in history] == ["user", "model", "user"]
    assert history[1] is first.candidates[0].content
    assert history[1].parts[0].thought_signature == b"signature-1"


async def test_tool_chat_keeps_every_turn_in_order_across_rounds() -> None:
    second = model_turn(call_part(call_id="call-2", signature=b"signature-2"))
    client, models = gemini(model_turn(call_part()), second, model_turn(text_part("Done.")))
    chat = tool_chat(client)
    step = await chat.send("what's that?")
    step = await chat.send_results([(step.calls[0], "one")])
    await chat.send_results([(step.calls[0], "two")])

    history = models.calls[2].contents
    assert [turn.role for turn in history] == ["user", "model", "user", "model", "user"]
    assert history[3] is second.candidates[0].content


async def test_the_players_words_go_first_as_a_user_turn() -> None:
    client, models = gemini(model_turn(text_part("Hi.")))
    await tool_chat(client).send("hello there")
    first = models.calls[0].contents[0]
    assert first.role == "user" and first.parts[0].text == "hello there"


async def test_tool_calls_come_back_with_their_id_name_and_args() -> None:
    client, _ = gemini(model_turn(call_part("look", "call-7")))
    step = await tool_chat(client).send("what's that?")
    assert step.calls == (ToolCall("look", {"question": "what's that?"}, "call-7"),)
    assert step.text == ""


async def test_a_tool_call_with_no_args_gets_an_empty_dict() -> None:
    bare = types.Part(function_call=types.FunctionCall(id="call-1", name="look"))
    client, _ = gemini(model_turn(bare))
    step = await tool_chat(client).send("what's that?")
    assert step.calls[0].args == {}


async def test_results_carry_the_calls_id_and_name_in_order() -> None:
    client, models = gemini(
        model_turn(call_part("look", "call-1"), call_part("point", "call-2")),
        model_turn(text_part("Done.")),
    )
    chat = tool_chat(client)
    step = await chat.send("what's that?")
    await chat.send_results(list(zip(step.calls, ["seen", "pointed"], strict=True)))

    results = models.calls[1].contents[-1]
    assert results.role == "user"
    sent = [part.function_response for part in results.parts]
    assert [(r.id, r.name, r.response) for r in sent] == [
        ("call-1", "look", {"result": "seen"}),
        ("call-2", "point", {"result": "pointed"}),
    ]


async def test_allow_tools_false_sets_mode_none() -> None:
    client, models = gemini(model_turn(call_part()), model_turn(text_part("Done.")))
    chat = tool_chat(client)
    step = await chat.send("what's that?")
    await chat.send_results([(step.calls[0], "A door.")], allow_tools=False)

    modes = [call.config.tool_config.function_calling_config.mode for call in models.calls]
    assert modes == [types.FunctionCallingConfigMode.AUTO, types.FunctionCallingConfigMode.NONE]


async def test_results_allow_more_tools_by_default() -> None:
    client, models = gemini(model_turn(call_part()), model_turn(text_part("Done.")))
    chat = tool_chat(client)
    step = await chat.send("what's that?")
    await chat.send_results([(step.calls[0], "A door.")])
    mode = models.calls[1].config.tool_config.function_calling_config.mode
    assert mode == types.FunctionCallingConfigMode.AUTO


async def test_automatic_function_calling_is_off_so_tools_run_in_our_loop() -> None:
    client, models = gemini(model_turn(call_part()), model_turn(text_part("Done.")))
    chat = tool_chat(client)
    step = await chat.send("what's that?")
    await chat.send_results([(step.calls[0], "A door.")], allow_tools=False)
    assert all(call.config.automatic_function_calling.disable is True for call in models.calls)


async def test_the_chat_sends_its_system_prompt_token_limit_and_tools() -> None:
    client, models = gemini(model_turn(text_part("Hi.")))
    await tool_chat(client).send("hello")
    call = models.calls[0]
    assert call.model == "test-model"
    assert call.config.system_instruction == "Be brief."
    assert call.config.max_output_tokens == 256
    declared = call.config.tools[0].function_declarations[0]
    assert (declared.name, declared.description) == ("look", "Look closer.")
    assert declared.parameters_json_schema == TOOLS[0].parameters


@pytest.mark.parametrize(
    "empty",
    [
        SimpleNamespace(candidates=[]),
        SimpleNamespace(candidates=None),
        SimpleNamespace(candidates=[SimpleNamespace(content=None)]),
        SimpleNamespace(candidates=[SimpleNamespace(content=types.Content(role="model"))]),
        SimpleNamespace(candidates=[SimpleNamespace(content=types.Content(parts=[]))]),
    ],
)
async def test_a_response_with_nothing_in_it_is_an_empty_response_error(empty: Any) -> None:
    client, _ = gemini(empty)
    with pytest.raises(LLMEmptyResponseError):
        await tool_chat(client).send("what's that?")


async def test_a_quota_error_on_a_tool_turn_counts_as_unavailable() -> None:
    client, _ = gemini(api_error(429))
    with pytest.raises(LLMUnavailableError, match="quota"):
        await tool_chat(client).send("what's that?")


async def test_a_quota_error_after_a_tool_counts_as_unavailable() -> None:
    client, _ = gemini(model_turn(call_part()), api_error(429))
    chat = tool_chat(client)
    step = await chat.send("what's that?")
    with pytest.raises(LLMUnavailableError):
        await chat.send_results([(step.calls[0], "A door.")])


async def test_other_api_errors_stay_as_they_are() -> None:
    # Only quota means "try again later". Anything else needs logging as a real failure.
    client, _ = gemini(api_error(500))
    with pytest.raises(errors.ServerError):
        await tool_chat(client).send("what's that?")


async def test_the_limiter_refuses_a_tool_turn_without_calling_the_model() -> None:
    client, models = gemini(model_turn(call_part()), rpm=1)
    chat = tool_chat(client)
    step = await chat.send("what's that?")
    with pytest.raises(LLMUnavailableError, match="rate limit"):
        await chat.send_results([(step.calls[0], "A door.")])
    assert len(models.calls) == 1


async def test_thought_parts_stay_out_of_the_reply() -> None:
    client, _ = gemini(
        model_turn(
            types.Part(text="They might mean the door.", thought=True),
            text_part("That's "),
            text_part("a door."),
        )
    )
    step = await tool_chat(client).send("what's that?")
    assert step.text == "That's a door."
    assert step.calls == ()


async def test_a_reply_can_hold_both_words_and_tool_calls() -> None:
    client, _ = gemini(model_turn(text_part("Checking."), call_part()))
    step = await tool_chat(client).send("what's that?")
    assert step.text == "Checking." and len(step.calls) == 1
