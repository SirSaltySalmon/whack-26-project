"""The latency report gives the pitch its numbers, so it must read every log line it claims to."""

import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from brain.loop_watch import WARN_MS
from scripts.latency_report import (
    FOUND,
    NOTHING_MATCHED,
    UNREADABLE,
    Kind,
    Samples,
    decode_log,
    loop_line,
    main,
    parse_lines,
    percentile,
    render,
    table_rows,
)

QUIET = "01:23:45 "
VERBOSE = "2026-11-08 01:23:45,123 INFO    brain.x: "
MESSAGES = [
    "Latency: player turn took 1430 ms",
    "Latency: event to bark 150 ms (health_low)",
    "Latency: end of turn to first audio 820 ms",
    "Latency: frame to bark 840 ms (health_low from reader: noticed in 690, spoke in 150)",
    "Latency: frame to first audio 2950 ms (danger_started from observer: noticed in 2400, "
    "spoke in 550)",
    "Event loop stalled 340 ms",
    "Event loop: longest stall 340 ms over 1800 s",
]
EVERY_KIND = {
    Kind("player turn"): [1430.0],
    Kind("event to bark"): [150.0],
    Kind("event to bark", "health_low"): [150.0],
    Kind("end of turn to first audio"): [820.0],
    Kind("frame to bark", "reader"): [840.0],
    Kind("frame to bark", "reader", "noticed"): [690.0],
    Kind("frame to bark", "reader", "spoke"): [150.0],
    Kind("frame to first audio", "observer"): [2950.0],
    Kind("frame to first audio", "observer", "noticed"): [2400.0],
    Kind("frame to first audio", "observer", "spoke"): [550.0],
}


@pytest.mark.parametrize("prefix", [QUIET, VERBOSE], ids=["quiet", "verbose"])
def test_every_format_is_read_after_either_prefix(prefix: str) -> None:
    samples = parse_lines(prefix + message for message in MESSAGES)
    assert samples.latency == EVERY_KIND
    assert samples.stalls == [340.0]
    assert samples.longest == [340.0]
    assert samples.watched_s == [1800.0]


def test_frame_times_split_by_source_with_their_parts() -> None:
    samples = parse_lines(
        [
            "Latency: frame to bark 840 ms (health_low from reader: noticed in 690, spoke in 150)",
            "Latency: frame to bark 3000 ms (health_low from observer: noticed in 2800, spoke in "
            "200)",
            "Latency: frame to bark 700 ms (boss_spawned from reader: noticed in 600, spoke in "
            "100)",
        ]
    )
    labels = [row[0] for row in table_rows(samples)]
    assert labels == [
        "frame to bark (observer)",
        "frame to bark (observer): noticed",
        "frame to bark (observer): spoke",
        "frame to bark (reader)",
        "frame to bark (reader): noticed",
        "frame to bark (reader): spoke",
    ]
    assert samples.latency[Kind("frame to bark", "reader", "noticed")] == [690.0, 600.0]
    assert samples.latency[Kind("frame to bark", "observer", "spoke")] == [200.0]


def test_rows_follow_the_kind_order_whatever_order_the_log_is_in() -> None:
    labels = [row[0] for row in table_rows(parse_lines(reversed(MESSAGES)))]
    assert labels[:4] == [
        "player turn",
        "event to bark",
        "event to bark (health_low)",
        "end of turn to first audio",
    ]
    assert labels[4].startswith("frame to bark") and labels[-1].startswith("frame to first audio")


def test_barks_get_a_row_per_event_after_their_total() -> None:
    samples = parse_lines(
        [
            "Latency: event to bark 0 ms (danger_started)",
            "Latency: event to bark 26 ms (health_low)",
            "Latency: event to bark 40 ms (health_low)",
        ]
    )
    assert [row[0] for row in table_rows(samples)] == [
        "event to bark",
        "event to bark (danger_started)",
        "event to bark (health_low)",
    ]
    assert samples.latency[Kind("event to bark")] == [0.0, 26.0, 40.0]
    assert samples.latency[Kind("event to bark", "health_low")] == [26.0, 40.0]


def test_a_measurement_the_console_wrapped_still_counts() -> None:
    # Windows PowerShell 5 wraps long lines at the console width, around noisy stderr.
    log = """02:44:05 Latency: event to
    bark 0 ms
    (danger_started)
    Latency: event to bark UNKNOWN ms
    noisy stderr
    02:44:06 Latency: frame to first audio 2950 ms (danger_started from observer: noticed in
    2400, spoke in 550)
    Event loop
    stalled 340 ms"""
    samples = parse_lines(log.splitlines())
    assert samples.latency == {
        Kind("event to bark"): [0.0],
        Kind("event to bark", "danger_started"): [0.0],
        Kind("frame to first audio", "observer"): [2950.0],
        Kind("frame to first audio", "observer", "noticed"): [2400.0],
        Kind("frame to first audio", "observer", "spoke"): [550.0],
    }
    assert samples.stalls == [340.0]


def test_nearest_rank_percentiles_on_a_known_list() -> None:
    values = [float(n) for n in range(100, 0, -10)]  # 10 values, deliberately unsorted
    assert percentile(values, 50) == 50.0
    assert percentile(values, 95) == 100.0
    assert percentile(values, 90) == 90.0
    assert percentile(values, 0) == 10.0
    assert percentile([7.0], 50) == percentile([7.0], 95) == 7.0
    with pytest.raises(ValueError):
        percentile([], 50)


def test_a_table_row_has_count_percentiles_and_max_in_whole_ms() -> None:
    lines = [f"Latency: player turn took {ms} ms" for ms in (100, 200, 300, 400, 1500)]
    assert table_rows(parse_lines(lines)) == [("player turn", 5, 300, 1500, 1500)]


def test_kinds_with_no_data_are_left_out() -> None:
    report = render(parse_lines(["Latency: event to bark 150 ms (health_low)"]))
    assert "| event to bark | 1 | 150 | 150 | 150 |" in report
    assert "player turn" not in report and "Event loop" not in report


def test_the_loop_line_counts_stalls_and_takes_the_longest_of_both_kinds() -> None:
    samples = parse_lines(
        [
            "Event loop stalled 120 ms",
            "Event loop stalled 450 ms",
            "Event loop: longest stall 450 ms over 1200 s",
            "Event loop: longest stall 80 ms over 600 s",
        ]
    )
    assert loop_line(samples) == (
        f"Event loop: 2 stalls over {WARN_MS:.0f} ms, longest 450 ms, over 1800 s watched."
    )
    # A run killed before its summary line still reports its stalls.
    assert loop_line(parse_lines(["Event loop stalled 130 ms"])) == (
        f"Event loop: 1 stalls over {WARN_MS:.0f} ms, longest 130 ms."
    )


def test_unrelated_lines_are_ignored() -> None:
    samples = parse_lines(
        [
            "01:23:45 Brain listening on ws://127.0.0.1:8765/ws",
            "01:23:46 Latency: something new 99 ms",
            "01:23:47 Player said: what's my latency: player turn took long",
            "",
            "Traceback (most recent call last):",
        ]
    )
    assert samples.empty()


def test_a_utf16_log_from_windows_powershell_is_decoded() -> None:
    text = "\r\n".join(QUIET + message for message in MESSAGES)
    for encoded in ("utf-16", "utf-16-be"):
        data = text.encode(encoded)
        if encoded == "utf-16-be":
            data = b"\xfe\xff" + data
        assert parse_lines(decode_log(data).splitlines()).latency == EVERY_KIND


def test_utf8_with_a_bom_or_bad_bytes_still_parses() -> None:
    data = b"\xef\xbb\xbf" + b"\xff\xfe junk\n" + MESSAGES[0].encode()
    # The stray bytes come after the BOM check, so they aren't mistaken for a UTF-16 BOM.
    assert parse_lines(decode_log(data).splitlines()).latency == {Kind("player turn"): [1430.0]}


def test_main_reads_files_and_prints_the_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = tmp_path / "a.log"
    second = tmp_path / "b.log"
    first.write_text("\n".join(MESSAGES[:3]), encoding="utf-8")
    second.write_bytes("\n".join(MESSAGES[3:]).encode("utf-16"))
    assert main([str(first), str(second)]) == FOUND
    out = capsys.readouterr().out
    assert out.startswith("| Kind | Count | p50 ms | p95 ms | Max ms |")
    assert "| frame to first audio (observer): noticed | 1 | 2400 | 2400 | 2400 |" in out
    assert out.rstrip().endswith("longest 340 ms, over 1800 s watched.")


def test_main_reads_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stdin = SimpleNamespace(buffer=io.BytesIO(MESSAGES[0].encode()))
    monkeypatch.setattr("sys.stdin", stdin)
    assert main(["-"]) == FOUND
    assert "| player turn | 1 | 1430 | 1430 | 1430 |" in capsys.readouterr().out


def test_empty_input_says_so_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty.log"
    empty.write_bytes(b"")
    assert main([str(empty)]) == NOTHING_MATCHED
    assert "No latency" in capsys.readouterr().out
    assert Samples().empty()


def test_a_missing_file_is_a_usage_error(tmp_path: Path) -> None:
    assert main([str(tmp_path / "missing.log")]) == UNREADABLE
