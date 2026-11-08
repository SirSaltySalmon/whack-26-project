"""Gemini client. Uses generate_content because it's stateless and available in the SDK version
Pipecat allows."""

import logging
from collections.abc import AsyncIterator, Sequence

from google import genai
from google.genai import errors, types

from brain.llm.base import (
    ChatTurn,
    Detail,
    Limiter,
    LLMEmptyResponseError,
    LLMUnavailableError,
    SchemaT,
    System,
    ToolCall,
    ToolDeclaration,
    ToolStep,
    merged_turns,
    system_text,
)

log = logging.getLogger(__name__)

QUOTA_EXCEEDED = 429
_RESOLUTIONS: dict[Detail, types.PartMediaResolutionLevel] = {
    "low": types.PartMediaResolutionLevel.MEDIA_RESOLUTION_LOW,
    "high": types.PartMediaResolutionLevel.MEDIA_RESOLUTION_HIGH,
}
# Gemini calls the assistant's side "model".
_ROLES = {"user": "user", "assistant": "model"}


def history_contents(history: Sequence[ChatTurn]) -> list[types.Content]:
    return [
        types.Content(role=_ROLES[turn.role], parts=[types.Part.from_text(text=turn.text)])
        for turn in merged_turns(history)
    ]


def add_user(contents: list[types.Content], text: str) -> None:
    """Joins the last message when that's theirs too, so turns still alternate."""
    part = types.Part.from_text(text=text)
    last = contents[-1] if contents else None
    if last is not None and last.role == "user" and last.parts is not None:
        last.parts.append(part)
    else:
        contents.append(types.Content(role="user", parts=[part]))


class GeminiClient:
    def __init__(
        self,
        model: str,
        api_key: str,
        limiter: Limiter,
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

    async def stream_text(
        self, system: System, prompt: str, max_tokens: int, history: Sequence[ChatTurn] = ()
    ) -> AsyncIterator[str]:
        self._acquire()
        # No cache breakpoints here, so the parts are just joined.
        config = types.GenerateContentConfig(
            system_instruction=system_text(system),
            max_output_tokens=max_tokens,
            thinking_config=self._thinking,
        )
        contents = history_contents(history)
        add_user(contents, prompt)
        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=self._model, contents=contents, config=config
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
        detail: Detail = "low",
    ) -> SchemaT:
        self._acquire()
        contents = [
            types.Part.from_bytes(
                data=image, mime_type=media_type, media_resolution=_RESOLUTIONS[detail]
            ),
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

    def tool_chat(
        self,
        system: System,
        tools: Sequence[ToolDeclaration],
        max_tokens: int,
        history: Sequence[ChatTurn] = (),
    ) -> "GeminiToolChat":
        return GeminiToolChat(self, system, tools, max_tokens, history)

    async def generate_with_tools(
        self,
        contents: list[types.Content],
        system: str,
        tools: Sequence[ToolDeclaration],
        max_tokens: int,
        allow_tools: bool,
    ) -> types.GenerateContentResponse:
        self._acquire()
        declarations = [
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters_json_schema=tool.parameters,
            )
            for tool in tools
        ]
        mode = (
            types.FunctionCallingConfigMode.AUTO
            if allow_tools
            else types.FunctionCallingConfigMode.NONE
        )
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            thinking_config=self._thinking,
            tools=[types.Tool(function_declarations=declarations)],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode=mode)
            ),
            # Tools run in our own loop, so the director can cancel them and every call is logged.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        try:
            return await self._client.aio.models.generate_content(
                model=self._model, contents=contents, config=config
            )
        except errors.APIError as exc:
            raise self._quota_error(exc) from exc


class GeminiToolChat:
    """Not streamed: a reply is collected before TTS anyway, and tool calls arrive whole."""

    def __init__(
        self,
        client: GeminiClient,
        system: System,
        tools: Sequence[ToolDeclaration],
        max_tokens: int,
        history: Sequence[ChatTurn] = (),
    ) -> None:
        self._client = client
        self._system = system_text(system)
        self._tools = tools
        self._max_tokens = max_tokens
        self._contents: list[types.Content] = history_contents(history)

    async def send(self, text: str) -> ToolStep:
        add_user(self._contents, text)
        return await self._generate(allow_tools=True)

    async def send_results(
        self, results: Sequence[tuple[ToolCall, str]], allow_tools: bool = True
    ) -> ToolStep:
        parts = [
            types.Part(
                function_response=types.FunctionResponse(
                    id=call.id, name=call.name, response={"result": output}
                )
            )
            for call, output in results
        ]
        self._contents.append(types.Content(role="user", parts=parts))
        return await self._generate(allow_tools)

    async def _generate(self, allow_tools: bool) -> ToolStep:
        response = await self._client.generate_with_tools(
            self._contents, self._system, self._tools, self._max_tokens, allow_tools
        )
        content = response.candidates[0].content if response.candidates else None
        if content is None or not content.parts:
            raise LLMEmptyResponseError("Gemini returned no content for a tool turn")
        # Kept exactly as received: Gemini 3 rejects a follow-up whose thought signatures are gone.
        self._contents.append(content)
        calls = tuple(
            ToolCall(
                name=part.function_call.name or "",
                args=dict(part.function_call.args or {}),
                id=part.function_call.id,
            )
            for part in content.parts
            if part.function_call
        )
        text = "".join(part.text for part in content.parts if part.text and not part.thought)
        return ToolStep(text=text, calls=calls)
