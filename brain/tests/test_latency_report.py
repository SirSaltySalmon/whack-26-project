from scripts.latency_report import report, samples


def test_parse_wrapped_and_interleaved_logs():
    log = """02:44:05 Latency: event to
    bark 0 ms
    (danger_started)
    Latency: event to bark UNKNOWN ms
    noisy stderr
    Latency: end of turn to first audio 797 ms
    ignored Latency: player turn took 641 ms
    Latency: event to bark 26 ms (health_low)"""
    assert samples(log) == {
        "event to bark": [0, 26],
        "event to bark (danger_started)": [0],
        "event to bark (health_low)": [26],
        "end of turn to first audio": [797],
        "player turn took": [641],
    }


def test_percentiles_use_nearest_rank():
    log = "\n".join(f"Latency: frame to bark {n} ms" for n in range(20, 0, -1))
    assert "| frame to bark | 20 | 10 | 19 | 20 |" in report(log)
