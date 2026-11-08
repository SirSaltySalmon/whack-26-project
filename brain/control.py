"""WebSocket link to the Control Center window: memory browsing, status, settings and shutdown.

Separate from OverlayLink because attaching a second socket there would replace the overlay's.
Requests only read memory: writes still go through MemoryService and its trust rules.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import WebSocket
from pydantic import ValidationError

from brain.events import EventBus, VoicePreviewRequested
from brain.memory.browse import Browse
from brain.server import OverlayLink
from shared.protocol import PROTOCOL_VERSION, BrainMessage, ControlReply, ControlRequestAdapter
from shared.protocol.control import (
    BrainStatus,
    ContextPreview,
    ControlError,
    ControlHello,
    ControlShutdown,
    GameView,
    MemoryContext,
    MemoryGames,
    MemoryListGames,
    MemoryQuery,
    MemoryResults,
    VoicePreview,
)
from shared.protocol.messages import MemoryToast, SettingsState, SettingsUpdate

log = logging.getLogger(__name__)

# Text, include history, limit, and the game: None for the one being played.
BrowseFn = Callable[[str, bool, int, str | None], Awaitable[Browse]]
RecallFn = Callable[[str, str | None], Awaitable[str]]


class ShutdownRequested(Exception):
    """Ends the run's task group when the Control Center stops the brain."""


async def stop_when(requested: asyncio.Event) -> None:
    await requested.wait()
    raise ShutdownRequested


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


class ControlLink:
    def __init__(
        self,
        overlay: OverlayLink,
        bus: EventBus,
        *,
        browse: BrowseFn,
        recall: RecallFn,
        games: Callable[[], Awaitable[list[GameView]]],
        status: Callable[[], BrainStatus],
        shutdown: Callable[[], None],
    ) -> None:
        self._overlay = overlay
        self._bus = bus
        self._browse = browse
        self._recall = recall
        self._games = games
        self._status = status
        self._shutdown = shutdown
        self._socket: WebSocket | None = None
        self._send_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._socket is not None

    def attach(self, socket: WebSocket) -> None:
        # One Control Center at a time; a newer window takes over.
        self._socket = socket

    def detach(self, socket: WebSocket) -> None:
        if self._socket is socket:
            self._socket = None

    async def send(self, message: ControlReply) -> None:
        socket = self._socket
        if socket is None:
            return
        try:
            async with self._send_lock:
                await socket.send_text(message.model_dump_json())
        except Exception:
            # The Control Center is optional; losing it must never disturb the overlay or the game.
            log.warning("Could not send %s to the Control Center", message.type, exc_info=True)

    async def mirror(self, message: BrainMessage) -> None:
        """Called for every overlay message. Forwards the ones the Control Center shows."""
        if isinstance(message, SettingsState | MemoryToast):
            await self.send(message)

    async def push_status(self) -> None:
        try:
            status = self._status()
        except Exception:
            log.exception("Could not build the brain status")
            return
        await self.send(status)

    async def handle_text(self, text: str) -> None:
        try:
            message = ControlRequestAdapter.validate_json(text)
        except ValidationError:
            log.warning("Rejected invalid Control Center message: %.200s", text)
            await self.send(ControlError(message="Invalid request"))
            return
        request_id = getattr(message, "request_id", None)
        try:
            await self._handle(message)
        except Exception as exc:
            log.exception("Control Center request %s failed", message.type)
            await self.send(ControlError(request_id=request_id, message=type(exc).__name__))

    async def _handle(self, message: object) -> None:
        match message:
            case ControlHello():
                if message.protocol_version != PROTOCOL_VERSION:
                    log.error(
                        "Protocol mismatch: control=%s brain=%s. Run gen:protocol.",
                        message.protocol_version,
                        PROTOCOL_VERSION,
                    )
                await self.send(self._overlay.settings_state())
                await self.push_status()
            case MemoryQuery():
                started = time.perf_counter()
                found = await self._browse(
                    message.text, message.include_history, message.limit, message.game
                )
                await self.send(
                    MemoryResults(
                        request_id=message.request_id,
                        facts=found.facts,
                        questions=found.questions,
                        notes=found.notes,
                        elapsed_ms=_elapsed_ms(started),
                    )
                )
            case ContextPreview():
                started = time.perf_counter()
                context = await self._recall(message.text, message.game)
                await self.send(
                    MemoryContext(
                        request_id=message.request_id,
                        context=context,
                        elapsed_ms=_elapsed_ms(started),
                    )
                )
            case MemoryListGames():
                await self.send(
                    MemoryGames(
                        request_id=message.request_id,
                        games=await self._games(),
                        current=self._status().game_title,
                        live=True,
                    )
                )
            case SettingsUpdate():
                await self._overlay.apply_settings(message.settings, "Control Center")
            case VoicePreview():
                self._bus.publish(VoicePreviewRequested(text=message.text))
            case ControlShutdown():
                log.info("The Control Center asked the brain to stop")
                self._shutdown()
