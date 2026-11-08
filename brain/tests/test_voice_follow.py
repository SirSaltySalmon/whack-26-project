"""The voice follows settings live: style changes, and pausing cuts off speech."""

import asyncio
import contextlib

from brain.events import Event, GameEvent, PlayerSpeech, SettingsChanged
from brain.tests.director_rig import settle
from brain.voice.follow import follow_settings, silenced
from shared.protocol.messages import Settings


class Recorder:
    def __init__(self) -> None:
        self.styles: list[str] = []
        self.urgent: list[bool] = []
        self.interruptions = 0

    async def set_style(self, style: str, urgent: bool = False) -> None:
        self.styles.append(style)
        self.urgent.append(urgent)

    async def interrupt(self) -> None:
        self.interruptions += 1


async def run(events: list[Event]) -> Recorder:
    queue: asyncio.Queue[Event] = asyncio.Queue()
    for event in events:
        queue.put_nowait(event)
    voice = Recorder()
    task = asyncio.create_task(follow_settings(queue, voice))
    await settle()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    return voice


def test_only_a_pause_silences() -> None:
    assert not silenced(Settings())
    assert silenced(Settings(paused=True))
    # Blind and muted, the partner still talks.
    assert not silenced(Settings(vision_enabled=False, mic_enabled=False))


async def test_pausing_interrupts_once_per_change() -> None:
    voice = await run(
        [
            SettingsChanged(settings=Settings(paused=True)),
            # Still paused, so nothing new to cut off.
            SettingsChanged(settings=Settings(paused=True, vision_enabled=False)),
            SettingsChanged(settings=Settings()),
            PlayerSpeech(transcript="ignored"),
            SettingsChanged(settings=Settings(vision_enabled=False)),
            SettingsChanged(settings=Settings(paused=True)),
        ]
    )
    assert voice.interruptions == 2


async def test_style_still_follows_the_settings() -> None:
    voice = await run([SettingsChanged(settings=Settings(voice_style="classic"))])
    assert voice.styles == ["classic"]
    assert voice.interruptions == 0


async def test_danger_speeds_the_voice_up_until_it_ends() -> None:
    voice = await run(
        [
            SettingsChanged(settings=Settings(voice_style="classic")),
            GameEvent(name="danger_started"),
            GameEvent(name="item_found"),  # Not about danger, so nothing changes
            GameEvent(name="danger_ended"),
        ]
    )
    assert voice.urgent == [False, True, False]
    assert voice.styles == ["classic"] * 3


async def test_turning_vision_off_ends_the_hurry() -> None:
    voice = await run(
        [GameEvent(name="danger_high"), SettingsChanged(settings=Settings(vision_enabled=False))]
    )
    assert voice.urgent == [True, False]
