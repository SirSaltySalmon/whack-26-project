"""WebSocket link to the overlay."""

import asyncio
import logging
from collections.abc import Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from brain.events import (
    CardClosedByPlayer,
    CardPageChanged,
    EventBus,
    OverlayConnected,
    QuestionAnswered,
    SettingsChanged,
)
from shared.protocol import PROTOCOL_VERSION, BrainMessage, OverlayMessageAdapter
from shared.protocol.messages import (
    CardClosed,
    CardNavigated,
    OverlayReady,
    OverlayRects,
    QuestionAnswer,
    Rect,
    Settings,
    SettingsState,
    SettingsUpdate,
    VoiceOption,
)

log = logging.getLogger(__name__)

# A website open in the player's browser can reach localhost sockets, so binding to
# 127.0.0.1 isn't enough. Browsers always send Origin, which lets us refuse them.
ALLOWED_ORIGINS = {"file://", "http://localhost:5173", "http://127.0.0.1:5173"}


class OverlayLink:
    """Tracks the connected overlay and what it has reported."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._socket: WebSocket | None = None
        self._send_lock = asyncio.Lock()
        self.rects: tuple[Rect, ...] = ()
        self.display_scale: float = 1.0
        self.settings = Settings()
        self.personalities: list[str] = []
        self.voices: list[VoiceOption] = []
        # Sees every message, even with no overlay connected, so a recording or replay logs them
        # all. It runs on the loop, so it must be quick.
        self.on_send: Callable[[BrainMessage], None] | None = None
        # Replay sets this to the recorded scale: the recorded rects are DIPs at that scale, so
        # masking must keep using it whatever scale the live overlay runs at.
        self.pinned_display_scale: float | None = None

    def _settings_state(self) -> SettingsState:
        return SettingsState(
            settings=self.settings, personalities=self.personalities, voices=self.voices
        )

    @property
    def connected(self) -> bool:
        return self._socket is not None

    async def send(self, message: BrainMessage) -> None:
        if self.on_send is not None:
            try:
                self.on_send(message)
            except Exception:
                # A recorder failure must never stop the overlay getting its messages.
                log.exception("on_send hook failed for %s; sending anyway", message.type)
        socket = self._socket
        if socket is None:
            log.debug("Overlay not connected; dropped %s", message.type)
            return
        async with self._send_lock:
            await socket.send_text(message.model_dump_json())

    def attach(self, socket: WebSocket) -> None:
        self._socket = socket

    def detach(self, socket: WebSocket) -> None:
        if self._socket is socket:
            self._socket = None
            self.rects = ()

    def _apply_display_scale(self, reported: float) -> None:
        pinned = self.pinned_display_scale
        if pinned is None:
            self.display_scale = reported
        elif reported != pinned:
            log.warning(
                "Overlay reports display scale %s but replay pinned %s; masking keeps the pin",
                reported,
                pinned,
            )

    async def handle_text(self, text: str) -> None:
        try:
            message = OverlayMessageAdapter.validate_json(text)
        except ValidationError:
            log.exception("Rejected invalid overlay message: %.200s", text)
            return

        match message:
            case OverlayReady():
                if message.protocol_version != PROTOCOL_VERSION:
                    log.error(
                        "Protocol mismatch: overlay=%s brain=%s. Run gen:protocol.",
                        message.protocol_version,
                        PROTOCOL_VERSION,
                    )
                self._apply_display_scale(message.display_scale)
                await self.send(self._settings_state())
                self._bus.publish(OverlayConnected(display_scale=message.display_scale))
            case OverlayRects():
                self.rects = tuple(item.rect for item in message.rects)
            case CardClosed():
                self._bus.publish(CardClosedByPlayer(card_id=message.card_id))
            case CardNavigated():
                self._bus.publish(
                    CardPageChanged(card_id=message.card_id, url=message.url, title=message.title)
                )
            case QuestionAnswer():
                self._bus.publish(
                    QuestionAnswered(question_id=message.question_id, answer=message.answer)
                )
            case SettingsUpdate():
                self.settings = message.settings
                await self.send(self._settings_state())
                self._bus.publish(SettingsChanged(settings=message.settings))


def create_app(link: OverlayLink) -> FastAPI:
    app = FastAPI(title="AI Gamer Partner brain")

    @app.websocket("/ws")
    async def overlay_socket(socket: WebSocket) -> None:
        origin = socket.headers.get("origin")
        if origin is not None and origin not in ALLOWED_ORIGINS:
            log.warning("Refused WebSocket from origin %s", origin)
            await socket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        await socket.accept()
        link.attach(socket)
        log.info("Overlay connected")
        try:
            while True:
                await link.handle_text(await socket.receive_text())
        except WebSocketDisconnect:
            log.info("Overlay disconnected")
        finally:
            link.detach(socket)

    return app
