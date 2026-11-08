import assert from "node:assert/strict";
import { test } from "node:test";
import { avatarToggles } from "./toggles.ts";

const names = (pressed: boolean[]) => pressed.map(String).join(",");

test("defaults show the partner running, listening and watching", () => {
  const toggles = avatarToggles({});
  assert.deepEqual(
    toggles.map((toggle) => toggle.name),
    ["pause", "mic", "vision"],
  );
  assert.equal(
    names(toggles.map((toggle) => toggle.pressed)),
    "false,false,false",
  );
});

test("each button flips only its own setting", () => {
  const settings = {
    personality: "calm",
    voice_style: "classic" as const,
    mic_enabled: true,
  };
  const [pause, mic, vision] = avatarToggles(settings);
  assert.deepEqual(pause?.next, { ...settings, paused: true });
  assert.deepEqual(mic?.next, { ...settings, mic_enabled: false });
  assert.deepEqual(vision?.next, { ...settings, vision_enabled: false });
});

test("paused, muted and blinded show pressed and click back", () => {
  const settings = { paused: true, mic_enabled: false, vision_enabled: false };
  const toggles = avatarToggles(settings);
  assert.equal(
    names(toggles.map((toggle) => toggle.pressed)),
    "true,true,true",
  );
  assert.equal(toggles[0]?.next.paused, false);
  assert.equal(toggles[1]?.next.mic_enabled, true);
  assert.equal(toggles[2]?.next.vision_enabled, true);
});
