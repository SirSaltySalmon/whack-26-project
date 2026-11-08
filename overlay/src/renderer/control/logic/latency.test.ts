import assert from "node:assert/strict";
import { test } from "node:test";
import {
  addLines,
  EMPTY_LATENCY,
  latencyRows,
  loopHealth,
  missesTarget,
  newLines,
  parseLatencyLine,
  percentile,
  RECENT_REACTIONS,
} from "./latency.ts";

// The brain's two log formats: quiet by default, and --verbose.
const quiet = (message: string): string => `01:23:45 ${message}`;
const verbose = (message: string): string =>
  `2026-11-08 01:23:45,123 INFO    brain.director.lines: ${message}`;
const LAUNCH = "> C:\\repo dir\\.venv\\Scripts\\python.exe -m brain --live";

for (const [name, prefix] of [
  ["quiet", quiet],
  ["verbose", verbose],
] as const) {
  test(`${name}: plain timings are read`, () => {
    assert.deepEqual(
      parseLatencyLine(prefix("Latency: player turn took 1430 ms")),
      { type: "sample", kind: "player turn", ms: 1430 },
    );
    assert.deepEqual(
      parseLatencyLine(prefix("Latency: event to bark 150 ms (health_low)")),
      { type: "sample", kind: "event to bark", ms: 150 },
    );
    assert.deepEqual(
      parseLatencyLine(prefix("Latency: end of turn to first audio 820 ms")),
      { type: "sample", kind: "end of turn to first audio", ms: 820 },
    );
    assert.deepEqual(parseLatencyLine(prefix("Event loop stalled 340 ms")), {
      type: "sample",
      kind: "event loop stall",
      ms: 340,
    });
  });

  test(`${name}: frame-to-voice reactions keep their split`, () => {
    const bark = prefix(
      "Latency: frame to bark 840 ms (health_low from reader: noticed in 690, spoke in 150)",
    );
    assert.deepEqual(parseLatencyLine(bark), {
      type: "reaction",
      reaction: {
        time: "01:23:45",
        kind: "frame to bark",
        event: "health_low",
        source: "reader",
        totalMs: 840,
        noticedMs: 690,
        spokeMs: 150,
      },
    });
    const audio = prefix(
      "Latency: frame to first audio 2950 ms (danger_started from observer: noticed in 2400, spoke in 550)",
    );
    assert.deepEqual(parseLatencyLine(audio), {
      type: "reaction",
      reaction: {
        time: "01:23:45",
        kind: "frame to first audio",
        event: "danger_started",
        source: "observer",
        totalMs: 2950,
        noticedMs: 2400,
        spokeMs: 550,
      },
    });
  });

  test(`${name}: the loop summary is read`, () => {
    assert.deepEqual(
      parseLatencyLine(prefix("Event loop: longest stall 340 ms over 1800 s")),
      { type: "loop summary", longestMs: 340, overS: 1800 },
    );
  });
}

test("a tiny negative clock difference, printed as -0, still counts", () => {
  const parsed = parseLatencyLine(
    quiet(
      "Latency: frame to bark 150 ms (health_low from reader: noticed in -0, spoke in 150)",
    ),
  );
  assert.equal(parsed?.type, "reaction");
  assert.equal(parsed?.type === "reaction" && parsed.reaction.noticedMs, -0);
});

test("unrelated lines are ignored", () => {
  for (const line of [
    "01:23:45 Brain listening on ws://127.0.0.1:8765",
    "01:23:45 Observer: 1 report in 640 ms",
    "you> what's that",
    "2026-11-08 01:23:45,123 WARNING brain.x: Latency: something new 5 ms",
    "Brain exited with code 0",
    "",
  ]) {
    assert.equal(parseLatencyLine(line), null, line);
  }
});

test("the launch line starts a new run, and other '>' lines don't", () => {
  assert.deepEqual(parseLatencyLine(LAUNCH), { type: "launch" });
  assert.equal(parseLatencyLine("> some other command"), null);
});

test("percentiles use the nearest rank on a known list", () => {
  const values = [100, 90, 80, 70, 60, 50, 40, 30, 20, 10];
  assert.equal(percentile(values, 50), 50);
  assert.equal(percentile(values, 95), 100);
  assert.equal(percentile(values, 90), 90);
  assert.equal(percentile(values, 0), 10);
  assert.equal(percentile([7], 95), 7);
  assert.equal(percentile([], 50), null);
  // The input isn't reordered, since React may still be showing it.
  assert.equal(values[0], 100);
});

test("frame kinds split by source, and rows come in a fixed order", () => {
  const state = addLines(EMPTY_LATENCY, [
    quiet("Event loop stalled 340 ms"),
    quiet("Latency: player turn took 1430 ms"),
    quiet(
      "Latency: frame to bark 840 ms (health_low from reader: noticed in 690, spoke in 150)",
    ),
    quiet(
      "Latency: frame to bark 1240 ms (danger_started from observer: noticed in 1100, spoke in 140)",
    ),
    quiet(
      "Latency: frame to bark 640 ms (health_low from reader: noticed in 500, spoke in 140)",
    ),
    quiet("Latency: event to bark 150 ms (health_low)"),
  ]);
  const rows = latencyRows(state);
  assert.deepEqual(
    rows.map((row) => [row.kind, row.source, row.count]),
    [
      ["frame to bark", "observer", 1],
      ["frame to bark", "reader", 2],
      ["event to bark", null, 1],
      ["player turn", null, 1],
      ["event loop stall", null, 1],
    ],
  );
  const reader = rows[1];
  assert.equal(reader?.lastMs, 640);
  assert.equal(reader?.p50Ms, 640);
  assert.equal(reader?.p95Ms, 840);
  assert.equal(reader?.targetMs, 1000);
  assert.equal(rows[3]?.targetMs, null);
});

test("reactions are newest first and capped", () => {
  const lines = Array.from({ length: RECENT_REACTIONS + 3 }, (_, i) =>
    quiet(
      `Latency: frame to first audio ${1000 + i} ms (e${i} from observer: noticed in 900, spoke in ${100 + i})`,
    ),
  );
  const state = addLines(EMPTY_LATENCY, lines);
  assert.equal(state.reactions.length, RECENT_REACTIONS);
  assert.equal(state.reactions[0]?.event, `e${RECENT_REACTIONS + 2}`);
  // Statistics still count every reaction, not just the listed ones.
  assert.equal(latencyRows(state)[0]?.count, RECENT_REACTIONS + 3);
});

test("a restart clears the numbers, and earlier states don't change", () => {
  const first = addLines(EMPTY_LATENCY, [
    quiet("Latency: event to bark 150 ms (health_low)"),
  ]);
  const second = addLines(first, [
    quiet("Latency: event to bark 450 ms (health_low)"),
  ]);
  assert.equal(latencyRows(first)[0]?.count, 1);
  assert.equal(latencyRows(second)[0]?.count, 2);

  const restarted = addLines(second, [
    "Brain exited with code 0",
    LAUNCH,
    quiet("Latency: player turn took 900 ms"),
  ]);
  assert.deepEqual(
    latencyRows(restarted).map((row) => row.kind),
    ["player turn"],
  );
  assert.equal(restarted.reactions.length, 0);
});

test("targets: at or over the target misses it, and no target never does", () => {
  assert.equal(missesTarget(299, 300), false);
  assert.equal(missesTarget(300, 300), true);
  assert.equal(missesTarget(5000, null), false);
});

test("loop health counts stalls and takes the longest from either line", () => {
  assert.deepEqual(loopHealth(EMPTY_LATENCY), {
    stalls: 0,
    longestMs: null,
    overS: null,
  });
  const stalled = addLines(EMPTY_LATENCY, [
    quiet("Event loop stalled 340 ms"),
    quiet("Event loop stalled 120 ms"),
  ]);
  assert.deepEqual(loopHealth(stalled), {
    stalls: 2,
    longestMs: 340,
    overS: null,
  });
  // A quiet run's summary still gives its longest wake-up, even under the warning level.
  const calm = addLines(EMPTY_LATENCY, [
    quiet("Event loop: longest stall 42 ms over 1800 s"),
  ]);
  assert.deepEqual(loopHealth(calm), { stalls: 0, longestMs: 42, overS: 1800 });
});

test("new lines are found as the log grows and as it drops old lines", () => {
  const a = ["1", "2", "3"];
  assert.deepEqual(newLines([], a), a);
  assert.deepEqual(newLines(a, a), []);
  assert.deepEqual(newLines(a, [...a, "4", "5"]), ["4", "5"]);
  // Capped at three lines: the oldest drop off the front.
  assert.deepEqual(newLines(a, ["3", "4", "5"]), ["4", "5"]);
  // Everything rolled past while the tab was closed.
  assert.deepEqual(newLines(a, ["7", "8", "9"]), ["7", "8", "9"]);
  // Repeated lines aren't mistaken for old ones.
  assert.deepEqual(newLines(["x", "x"], ["x", "x", "x"]), ["x"]);
});
