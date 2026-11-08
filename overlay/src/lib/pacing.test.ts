import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { partnerSettings, sanitizeConfig } from "./launcher.ts";
import {
  clampPacing,
  DEFAULT_PACING,
  fullPacing,
  PACING_MAX,
  PACING_PRESETS,
  samePacing,
} from "./pacing.ts";

test("the defaults match the brain's, from the protocol schema", () => {
  const schemaPath = new URL(
    "../../../shared/protocol/schema.json",
    import.meta.url,
  );
  const schema = JSON.parse(readFileSync(schemaPath, "utf8")) as {
    $defs: { Pacing: { properties: Record<string, { default: number }> } };
  };
  const brain = Object.fromEntries(
    Object.entries(schema.$defs.Pacing.properties).map(([key, field]) => [
      key,
      field.default,
    ]),
  );
  assert.deepEqual(brain, DEFAULT_PACING);
});

test("missing or junk pacing falls back to the defaults field by field", () => {
  assert.deepEqual(fullPacing(undefined), DEFAULT_PACING);
  assert.deepEqual(fullPacing([1, 2]), DEFAULT_PACING);
  assert.deepEqual(fullPacing({ event_gap_s: "2", advice_gap_s: 30 }), {
    ...DEFAULT_PACING,
    advice_gap_s: 30,
  });
});

test("values are kept between zero and the cap", () => {
  assert.equal(clampPacing("question_gap_s", -5), 0);
  assert.equal(clampPacing("event_gap_s", 1e9), PACING_MAX.event_gap_s);
  assert.equal(
    clampPacing("advice_gap_s", Number.NaN),
    DEFAULT_PACING.advice_gap_s,
  );
  assert.equal(clampPacing("question_quiet_s", 7.5), 7.5);
});

test("a zero tip gap survives, because it means tips are off", () => {
  assert.equal(fullPacing({ advice_gap_s: 0 }).advice_gap_s, 0);
});

test("pacing survives a save and a restart", () => {
  const saved = partnerSettings({ pacing: { question_gap_s: 15 } });
  assert.equal(
    sanitizeConfig({ settings: saved }).settings.pacing.question_gap_s,
    15,
  );
  assert.deepEqual(partnerSettings({}).pacing, DEFAULT_PACING);
});

test("presets are told apart, and Default is the brain's default", () => {
  const names = PACING_PRESETS.filter((preset) =>
    samePacing(preset.pacing, DEFAULT_PACING),
  ).map((preset) => preset.name);
  assert.deepEqual(names, ["Default"]);
});
