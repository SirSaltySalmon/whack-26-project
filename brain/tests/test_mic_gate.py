"""Push to talk, the echo window without headphones, and logging setting changes."""

import logging
import time

import pytest

from brain.events import EventBus, PlayerStartedSpeaking
from brain.server import OverlayLink
from brain.tests.fakes import drain
from brain.voice.mic_gate import ModeLog, PushToTalk, echo_window, key_code
from shared.protocol.messages import Settings

pytest.importorskip("pyaudio")
from brain.tests.test_voice import _voice  # noqa: E402


@pytest.mark.parametrize(
    ("name", "code"),
    [("`", 0xC0), ("backtick", 0xC0), ("mouse4", 0x05), ("F8", 0x77), ("v", 0x56), ("7", 0x37)],
)
def test_key_names_become_windows_key_codes(name: str, code: int) -> None:
    assert key_code(name) == code


def test_an_unknown_key_name_is_none() -> None:
    assert key_code("hyperspace") is None
    assert key_code("f25") is None


def test_push_to_talk_reads_the_key_it_was_given() -> None:
    down: set[int] = set()
    ptt = PushToTalk("mouse4", lambda code: code in down)
    assert not ptt.held()
    down.add(0x05)
    assert ptt.held()


def test_push_to_talk_with_a_bad_key_stays_up_and_says_so_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ptt = PushToTalk("hyperspace", lambda _code: True)
    assert not ptt.held() and not ptt.held()
    assert caplog.text.count("Push to talk can't read") == 1


def test_the_echo_window_covers_speech_and_its_tail() -> None:
    assert echo_window(True, None, 0.8, now=10.0)
    assert echo_window(False, 9.5, 0.8, now=10.0)
    assert not echo_window(False, 9.0, 0.8, now=10.0)
    assert not echo_window(False, None, 0.8, now=10.0)


def test_mode_changes_are_logged_once_each(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    modes = ModeLog()
    for _ in range(3):
        modes.note(True, True, "`")
    assert caplog.text.count("No headphones on") == 1
    assert caplog.text.count("Push to talk on: hold ` to speak") == 1


def _settings(voice: object, **changes: bool) -> None:
    link = voice._link  # type: ignore[attr-defined]
    link.settings = link.settings.model_copy(update=changes)


def test_push_to_talk_lets_the_mic_through_only_while_the_key_is_held() -> None:
    voice = _voice(half_duplex=False)
    held = [False]
    voice._push_to_talk = PushToTalk("`", lambda _code: held[0])
    assert not voice.mic_muted()
    _settings(voice, push_to_talk=True)
    assert voice.mic_muted()
    held[0] = True
    assert not voice.mic_muted()


async def test_without_headphones_a_late_start_of_turn_does_not_cut_the_partner_off() -> None:
    # Flux reports a start of turn about 0.5 s late, from sound heard just before the mute.
    voice = _voice(half_duplex=False)
    bus = EventBus()
    events = bus.subscribe()
    voice._bus = bus
    voice.user_speaking = False
    _settings(voice, no_headphones=True)
    voice.bot_speaking = True
    await voice.on_start_of_turn()
    assert not voice.user_speaking
    assert not [e for e in drain(events) if isinstance(e, PlayerStartedSpeaking)]
    # Just after it stops talking, the room still rings, so it's still ignored.
    voice.bot_speaking = False
    voice._bot_stopped_at = time.monotonic()
    await voice.on_start_of_turn()
    assert not voice.user_speaking


async def test_settings_changes_are_logged_with_where_they_came_from(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    link = OverlayLink(EventBus())
    await link.apply_settings(Settings(no_headphones=True), "Control Center")
    assert "Settings from the Control Center: no_headphones=True" in caplog.text
    caplog.clear()
    await link.apply_settings(Settings(no_headphones=True), "overlay")
    assert "Settings from" not in caplog.text  # Nothing changed
