"""WebSocket link to the overlay."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from brain.events import (
    CardClosedByPlayer,
    CardPageChanged,
    EventBus,
    OverlayConnected,
    PageContentReceived,
    PlayerSpeech,
    PlayerStartedSpeaking,
    QuestionAnswered,
    SettingsChanged,
)
from shared.protocol import PROTOCOL_VERSION, BrainMessage, OverlayMessageAdapter
from shared.protocol.messages import (
    CardClosed,
    CardNavigated,
    OverlayReady,
    OverlayRects,
    PageContent,
    PlayerText,
    QuestionAnswer,
    Rect,
    Settings,
    SettingsState,
    SettingsUpdate,
    VoiceOption,
)

if TYPE_CHECKING:
    from brain.control import ControlLink

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
        # What the overlay reported: its devicePixelRatio.
        self.reported_scale: float = 1.0
        # Set when frames aren't in physical pixels, as with mss on macOS.
        self.frame_scale_override: float | None = None
        self.settings = Settings()
        self.personalities: list[str] = []
        self.voices: list[VoiceOption] = []
        # Sees every message, even with no overlay connected, so a recording or replay logs them
        # all. It runs on the loop, so it must be quick.
        self.on_send: Callable[[BrainMessage], None] | None = None
        # The Control Center's copy of the messages it shows. Separate from on_send, which the
        # recorder owns.
        self.mirror: Callable[[BrainMessage], Awaitable[None]] | None = None
        # Replay sets this to the recorded scale: the recorded rects are DIPs at that scale, so
        # masking must keep using it whatever scale the live overlay runs at.
        self.pinned_display_scale: float | None = None

    def settings_state(self) -> SettingsState:
        return SettingsState(
            settings=self.settings, personalities=self.personalities, voices=self.voices
        )

    @property
    def display_scale(self) -> float:
        """Frame pixels per overlay DIP: what masking and pointing convert by.

        A replay's pin wins, because its rects were recorded at that scale. Then a capture
        override, then what the overlay reported.
        """
        if self.pinned_display_scale is not None:
            return self.pinned_display_scale
        if self.frame_scale_override is not None:
            return self.frame_scale_override
        return self.reported_scale

    @display_scale.setter
    def display_scale(self, value: float) -> None:
        # Replay sets it from the recording, as it did when this was a plain field.
        self.reported_scale = value

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
        if self.mirror is not None:
            await self.mirror(message)
        socket = self._socket
        if socket is None:
            log.debug("Overlay not connected; dropped %s", message.type)
            return
        async with self._send_lock:
            try:
                await socket.send_text(message.model_dump_json())
            except (WebSocketDisconnect, RuntimeError):
                # The overlay closed between the check above and this send. Same as not being
                # connected: dropped. Raising here would end whatever sent it, such as the debug
                # view's loop, which then wouldn't come back when the overlay reconnects.
                log.info("Overlay went away; dropped %s", message.type)
                self.detach(socket)

    def attach(self, socket: WebSocket) -> None:
        self._socket = socket

    def detach(self, socket: WebSocket) -> None:
        if self._socket is socket:
            self._socket = None
            self.rects = ()

    def _apply_display_scale(self, reported: float) -> None:
        self.reported_scale = reported
        pinned = self.pinned_display_scale
        if pinned is not None and reported != pinned:
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
                await self.send(self.settings_state())
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
                await self.apply_settings(message.settings)
            case PlayerText():
                await self._typed_turn(message.text)
            case PageContent():
                self._bus.publish(
                    PageContentReceived(
                        request_id=message.request_id,
                        card_id=message.card_id,
                        url=message.url,
                        title=message.title,
                        text=message.text,
                        visible_text=message.visible_text,
                        truncated=message.truncated,
                    )
                )

    async def _typed_turn(self, text: str) -> None:
        transcript = " ".join(text.split())
        if not transcript:
            return
        log.info("Player (typed in overlay): %s", transcript)
        # The same pair of events speech sends, so a typed turn barges in and is answered alike.
        self._bus.publish(PlayerStartedSpeaking())
        # Real voice never sends these together, so subscribers get a tick between them here too.
        await asyncio.sleep(0)
        self._bus.publish(PlayerSpeech(transcript=transcript))

    async def apply_settings(self, settings: Settings) -> None:
        """From the overlay's settings card or the Control Center. Both hear the new state."""
        self.settings = settings
        await self.send(self.settings_state())
        self._bus.publish(SettingsChanged(settings=settings))


async def _refuse_websites(socket: WebSocket) -> bool:
    """Returns True if the socket was refused."""
    origin = socket.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        log.warning("Refused WebSocket from origin %s", origin)
        await socket.close(code=status.WS_1008_POLICY_VIOLATION)
        return True
    return False


def create_app(link: OverlayLink, control: "ControlLink | None" = None) -> FastAPI:
    app = FastAPI(title="AI Gamer Partner brain")

    @app.websocket("/ws")
    async def overlay_socket(socket: WebSocket) -> None:
        if await _refuse_websites(socket):
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

    if control is not None:

        @app.websocket("/control")
        async def control_socket(socket: WebSocket) -> None:
            if await _refuse_websites(socket):
                return

            await socket.accept()
            control.attach(socket)
            log.info("Control Center connected")
            try:
                while True:
                    await control.handle_text(await socket.receive_text())
            except WebSocketDisconnect:
                log.info("Control Center disconnected")
            finally:
                control.detach(socket)

    return app
