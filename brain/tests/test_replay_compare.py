from pathlib import Path
from typing import Any

import pytest

from brain.replay.compare import compare, load_messages, main, normalize, summarize
from brain.replay.format import MESSAGES, MessageRecord, jsonl_line
from shared.protocol import BrainMessage
from shared.protocol.messages import (
    AvatarState,
    CardShow,
    PointerFly,
    PointerHide,
    QuestionAsk,
    Rect,
    Settings,
    SettingsState,
    SubtitleChunk,
    VoiceOption,
)


def run(tag: str, shift: float = 0.0, line: str = "That looks rough.") -> list[BrainMessage]:
    """One run's messages. `tag` changes every ID and `shift` every position and lifetime, as
    they would between two runs that behaved the same."""
    box = Rect(x=100 + shift, y=200 + shift, width=40 + shift, height=30 + shift)
    return [
        AvatarState(state="talking"),
        SubtitleChunk(utterance_id=f"utt-{tag}", text=line, final=True),
        CardShow(card_id=f"card-{tag}", title="Slime", body="A bouncy enemy."),
        QuestionAsk(question_id=f"q-{tag}", text="Is that your base?", options=["Yes", "No"]),
        PointerFly(
            x=90 + shift, y=180 + shift, label="Slime", target=box, ttl_ms=int(2000 + shift)
        ),
        PointerHide(),
    ]


def as_json(messages: list[BrainMessage]) -> list[dict[str, Any]]:
    return [message.model_dump(mode="json") for message in messages]


def write_run(path: Path, messages: list[BrainMessage], start: float = 0.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for index, message in enumerate(as_json(messages)):
            file.write(jsonl_line(MessageRecord(t=start + index * 0.7, message=message)))
    return path


def test_runs_that_differ_only_in_timing_ids_ttl_and_rects_match(tmp_path: Path) -> None:
    a = write_run(tmp_path / "a.jsonl", run("first"), start=0.0)
    b = write_run(tmp_path / "b.jsonl", run("second", shift=17.5), start=3.2)
    assert compare(load_messages(a), load_messages(b)) == []


def test_normalize_drops_ids_and_geometry_at_any_depth_but_keeps_content() -> None:
    state = SettingsState(
        settings=Settings(personality="protective", voice_id="voice-2"),
        personalities=["supportive", "protective"],
        voices=[VoiceOption(name="Ava", id="voice-1")],
    )
    assert normalize(state.model_dump(mode="json")) == {
        "type": "settings.state",
        "settings": {
            "proactive": True,
            "personality": "protective",
            "mic_enabled": True,
            "voice_style": "expressive",
        },
        "personalities": ["supportive", "protective"],
        "voices": [{"name": "Ava"}],
    }
    pointer = PointerFly(x=1, y=2, label="Slime", target=Rect(x=1, y=2, width=3, height=4))
    assert normalize(pointer.model_dump(mode="json")) == {"type": "pointer.fly", "label": "Slime"}


def test_summary_is_one_line_with_the_type_first_and_sorted_keys() -> None:
    message = SubtitleChunk(utterance_id="u1", text="Hi.\nThere.", final=True)
    assert summarize(message.model_dump(mode="json")) == (
        'subtitle.chunk {"final": true, "text": "Hi.\\nThere."}'
    )


def test_a_changed_subtitle_shows_both_lines() -> None:
    diff = compare(as_json(run("a")), as_json(run("b", line="Watch out!")))
    assert '-subtitle.chunk {"final": true, "text": "That looks rough."}' in diff
    assert '+subtitle.chunk {"final": true, "text": "Watch out!"}' in diff


def test_a_changed_type_is_a_difference() -> None:
    changed = run("b")
    changed[-1] = AvatarState(state="idle")
    diff = compare(as_json(run("a")), as_json(changed))
    assert "-pointer.hide {}" in diff
    assert '+avatar.state {"state": "idle"}' in diff


@pytest.mark.parametrize("change", ["missing", "extra"])
def test_a_missing_or_extra_message_is_a_difference(change: str) -> None:
    shorter = run("b")[:-1]
    a, b = (run("a"), shorter) if change == "missing" else (shorter, run("a"))
    diff = compare(as_json(a), as_json(b))
    assert ("-pointer.hide {}" if change == "missing" else "+pointer.hide {}") in diff


def test_main_returns_0_when_runs_match(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a = write_run(tmp_path / "a.jsonl", run("a"))
    b = write_run(tmp_path / "b.jsonl", run("b", shift=3.0), start=9.0)
    assert main([str(a), str(b)]) == 0
    assert "Match: 6 messages." in capsys.readouterr().out


def test_main_returns_1_and_prints_the_diff_when_runs_differ(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = write_run(tmp_path / "a.jsonl", run("a"))
    b = write_run(tmp_path / "b.jsonl", run("b", line="Watch out!"))
    assert main([str(a), str(b)]) == 1
    out = capsys.readouterr().out
    assert f"--- {a}" in out and f"+++ {b}" in out
    assert '+subtitle.chunk {"final": true, "text": "Watch out!"}' in out


def test_main_accepts_session_directories(tmp_path: Path) -> None:
    write_run(tmp_path / "one" / MESSAGES, run("a"))
    write_run(tmp_path / "two" / MESSAGES, run("b"))
    assert main([str(tmp_path / "one"), str(tmp_path / "two")]) == 0


def test_main_returns_2_for_a_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = write_run(tmp_path / "a.jsonl", run("a"))
    missing = tmp_path / "nope.jsonl"
    assert main([str(a), str(missing)]) == 2
    assert str(missing) in capsys.readouterr().err


@pytest.mark.parametrize("argv", [[], ["only-one.jsonl"], ["a", "b", "c"], ["--bogus", "a", "b"]])
def test_main_returns_2_for_a_usage_error(argv: list[str]) -> None:
    assert main(argv) == 2


def test_a_truncated_last_line_is_skipped(tmp_path: Path) -> None:
    whole = write_run(tmp_path / "whole.jsonl", run("a"))
    cut = write_run(tmp_path / "cut.jsonl", run("b"))
    with cut.open("a", encoding="utf-8") as file:
        file.write('{"t": 9.1, "message": {"type": "subtitle.chu')
    assert len(load_messages(cut)) == 6
    assert main([str(whole), str(cut)]) == 0
