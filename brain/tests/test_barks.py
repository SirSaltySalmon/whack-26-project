"""The bark bank: generate once per line and voice, then serve from RAM with no I/O."""

import shutil
from pathlib import Path

import pytest

from brain.director.personalities import Personality, PersonalityBook
from brain.tests.fakes import FakeBarkSynth
from brain.voice.barks import BarkBank, split_pcm

MODEL = "eleven_test"
RATE = 24000
BOOK = PersonalityBook(
    default="calm",
    personalities={
        "calm": Personality(tone="Calm.", lines={"looking": ["One sec."], "died": ["Oof.", "Ow."]}),
        # Shares a line with calm, which only needs generating once.
        "loud": Personality(tone="Loud.", lines={"looking": ["One sec."], "danger": ["Run!"]}),
    },
)
LINES = {"One sec.", "Oof.", "Ow.", "Run!"}


def _bank(cache: Path, synth: FakeBarkSynth | None) -> BarkBank:
    return BarkBank(BOOK, synth, cache, MODEL, RATE)


async def test_a_cache_miss_generates_each_line_once(tmp_path: Path) -> None:
    synth = FakeBarkSynth()
    bank = _bank(tmp_path, synth)
    await bank.prepare("voiceA")
    assert {call[0] for call in synth.calls} == LINES
    assert len(synth.calls) == len(LINES)
    assert {call[1:] for call in synth.calls} == {("voiceA", MODEL, RATE)}
    await bank.prepare("voiceA")
    assert len(synth.calls) == len(LINES)


async def test_a_new_bank_loads_from_disk_without_generating(tmp_path: Path) -> None:
    await _bank(tmp_path, FakeBarkSynth()).prepare("voiceA")
    synth = FakeBarkSynth()
    bank = _bank(tmp_path, synth)
    await bank.prepare("voiceA")
    assert synth.calls == []
    bark = bank.get("calm", "died", 1, "voiceA")
    assert bark is not None and bark.text == "Ow." and bark.sample_rate == RATE


async def test_files_are_named_by_voice_model_and_text(tmp_path: Path) -> None:
    bank = _bank(tmp_path, FakeBarkSynth())
    await bank.prepare("voiceA")
    path = bank.path("voiceA", "Run!")
    assert path.parent == tmp_path / "voiceA"
    assert path.name.startswith(f"{MODEL}-{RATE}-") and path.suffix == ".pcm"
    assert path.is_file()


async def test_get_is_none_until_ready_and_then_needs_no_disk(tmp_path: Path) -> None:
    bank = _bank(tmp_path, FakeBarkSynth())
    assert bank.get("calm", "looking", 0, "voiceA") is None
    await bank.prepare("voiceA")
    shutil.rmtree(tmp_path / "voiceA")  # get must not touch the disk
    bark = bank.get("calm", "looking", 0, "voiceA")
    assert bark is not None and bark.text == "One sec." and len(bark.pcm) == RATE // 50 * 2


async def test_each_voice_has_its_own_folder_and_barks(tmp_path: Path) -> None:
    synth = FakeBarkSynth()
    bank = _bank(tmp_path, synth)
    await bank.prepare("voiceA")
    assert bank.get("calm", "died", 0, "voiceB") is None
    await bank.prepare("voiceB")
    assert len(synth.calls) == 2 * len(LINES)
    assert len(list((tmp_path / "voiceB").glob("*.pcm"))) == len(LINES)
    assert bank.get("calm", "died", 0, "voiceB") is not None


async def test_without_a_synth_nothing_is_generated(tmp_path: Path) -> None:
    bank = _bank(tmp_path, None)
    await bank.prepare("voiceA")
    assert bank.get("calm", "looking", 0, "voiceA") is None
    assert not (tmp_path / "voiceA").exists()


async def test_a_kind_the_personality_lacks_gives_none(tmp_path: Path) -> None:
    bank = _bank(tmp_path, FakeBarkSynth())
    await bank.prepare("voiceA")
    assert bank.get("calm", "danger", 0, "voiceA") is None


async def test_a_voice_id_that_isnt_a_plain_name_is_refused(tmp_path: Path) -> None:
    synth = FakeBarkSynth()
    await _bank(tmp_path / "barks", synth).prepare("../escape")
    assert synth.calls == []
    assert not (tmp_path / "escape").exists()


async def test_a_failing_synth_stops_and_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    synth = FakeBarkSynth(fail=True)
    bank = _bank(tmp_path, synth)
    await bank.prepare("voiceA")
    assert len(synth.calls) == 1  # One failure, not one per line
    assert "Couldn't generate bark" in caplog.text
    synth.fail = False
    await bank.prepare("voiceA")  # The next voice change tries again
    assert bank.get("loud", "danger", 0, "voiceA") is not None


async def test_characters_spent_are_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    await _bank(tmp_path, FakeBarkSynth()).prepare("voiceA")
    spent = sum(len(text) for text in LINES)
    assert f"{len(LINES)} generated ({spent} ElevenLabs characters)" in caplog.text


def test_pcm_splits_into_whole_samples() -> None:
    chunks = split_pcm(bytes(2000), 24000, chunk_ms=20)
    assert [len(chunk) for chunk in chunks] == [960, 960, 80]
    assert split_pcm(b"", 24000) == []
