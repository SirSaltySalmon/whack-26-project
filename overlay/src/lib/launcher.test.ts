import assert from "node:assert/strict";
import { test } from "node:test";
import {
  allVoices,
  brainArgs,
  partnerSettings,
  DEFAULT_CONFIG,
  sanitizeConfig,
  toEnv,
  type LauncherConfig,
} from "./launcher.ts";
import { DEFAULT_PACING } from "./pacing.ts";

const config = (change: Partial<LauncherConfig> = {}): LauncherConfig => ({
  ...DEFAULT_CONFIG,
  ...change,
});

test("empty values are left out so .env still applies", () => {
  const env = toEnv(config({ typed: false }), { GEMINI_API_KEY: "  " }, []);
  assert.deepEqual(env, {
    PYTHONUNBUFFERED: "1",
    PYTHONIOENCODING: "utf-8",
  });
});

test("keys, game and voice choices reach the environment", () => {
  const env = toEnv(
    config({
      gameProcess: " Terraria ",
      gameTitle: "Terraria",
      customVoices: [{ name: "Mine", id: "v2" }],
      tuning: {
        halfDuplex: true,
        keyterms: ["Eye of Cthulhu"],
        micIndex: 2,
        speakerIndex: null,
      },
      settings: {
        proactive: true,
        personality: "supportive",
        voice_id: "v2",
        mic_enabled: true,
        no_headphones: false,
        push_to_talk: false,
        voice_style: "classic",
        memory_search: "hybrid",
        custom_instructions: "Avoid spoilers",
        pacing: DEFAULT_PACING,
      },
    }),
    { GEMINI_API_KEY: "g-key", ANTHROPIC_API_KEY: "a-key" },
    [{ name: "Ava", id: "v1" }],
  );
  assert.equal(env.GEMINI_API_KEY, "g-key");
  assert.equal(env.ANTHROPIC_API_KEY, "a-key");
  assert.equal(env.DEEPGRAM_API_KEY, undefined);
  assert.equal(env.GAME_PROCESS, "Terraria");
  assert.equal(env.ELEVENLABS_VOICE_ID, "v2");
  assert.equal(env.VOICE_HALF_DUPLEX, "true");
  assert.equal(env.MIC_DEVICE_INDEX, "2");
  assert.equal(env.SPEAKER_DEVICE_INDEX, undefined);
  assert.deepEqual(JSON.parse(env.STT_KEYTERMS ?? ""), ["Eye of Cthulhu"]);
  // Adding a voice keeps the ones .env offered.
  assert.deepEqual(JSON.parse(env.VOICE_OPTIONS ?? ""), [
    { name: "Ava", id: "v1" },
    { name: "Mine", id: "v2" },
  ]);
});

test("command line follows the mode", () => {
  assert.deepEqual(brainArgs(config({ typed: true, record: true })), [
    "-m",
    "brain",
    "--live",
    "--record",
    "--type",
  ]);
  // Recording only makes sense live.
  assert.deepEqual(
    brainArgs(
      config({
        mode: "replay",
        replayDir: " sessions/a ",
        record: true,
        typed: false,
        verbose: true,
      }),
    ),
    ["-m", "brain", "--replay", "sessions/a", "--verbose"],
  );
});

test("saved files are repaired field by field", () => {
  const repaired = sanitizeConfig({
    mode: "sideways",
    gameTitle: "Terraria",
    typed: "yes",
    customVoices: [{ name: "Ok", id: "v" }, { name: 3 }],
    tuning: { micIndex: -1, speakerIndex: 1, keyterms: ["a", 2] },
    settings: {
      personality: "protective",
      voice_id: 5,
      mic_enabled: "no",
      voice_style: "loud",
      memory_search: "telepathy",
      pacing: { event_gap_s: "soon", question_gap_s: 12 },
    },
  });
  assert.equal(repaired.mode, "live");
  assert.equal(repaired.gameTitle, "Terraria");
  assert.equal(repaired.typed, DEFAULT_CONFIG.typed);
  assert.deepEqual(repaired.customVoices, [{ name: "Ok", id: "v" }]);
  assert.deepEqual(repaired.tuning, {
    halfDuplex: false,
    keyterms: ["a"],
    micIndex: null,
    speakerIndex: 1,
  });
  assert.deepEqual(repaired.settings, {
    proactive: true,
    personality: "protective",
    voice_id: null,
    mic_enabled: true,
    no_headphones: false,
    push_to_talk: false,
    voice_style: "expressive",
    memory_search: "keyword",
    custom_instructions: "",
    pacing: { ...DEFAULT_PACING, question_gap_s: 12 },
  });
  assert.deepEqual(sanitizeConfig(null), DEFAULT_CONFIG);
});

test("the memory search choice survives a save and a restart", () => {
  const saved = partnerSettings({ memory_search: "semantic" });
  assert.equal(
    sanitizeConfig({ settings: saved }).settings.memory_search,
    "semantic",
  );
  assert.equal(partnerSettings({}).memory_search, "keyword");
});

test("a pause or a blinded partner is never saved", () => {
  const saved = partnerSettings({ paused: true, vision_enabled: false });
  // Sent on connect without them, so the brain keeps its own: unpaused and seeing at startup.
  assert.equal("paused" in saved, false);
  assert.equal("vision_enabled" in saved, false);
});

test("typing instead of talking survives a save and a restart", () => {
  // Dropping it would send the default with the next change, and the mic would come back on.
  const saved = partnerSettings({ personality: "calm", mic_enabled: false });
  assert.equal(saved.mic_enabled, false);
  assert.equal(sanitizeConfig({ settings: saved }).settings.mic_enabled, false);
  assert.equal(partnerSettings({}).mic_enabled, true);
});

test("voices from .env come first and repeats are dropped", () => {
  assert.deepEqual(
    allVoices(
      [{ name: "Ava", id: "v1" }],
      [
        { name: "Ava again", id: "v1" },
        { name: "B", id: "v2" },
      ],
    ),
    [
      { name: "Ava", id: "v1" },
      { name: "B", id: "v2" },
    ],
  );
});

test("custom instructions survive settings conversion and saved configuration", () => {
  const saved = sanitizeConfig({
    settings: { custom_instructions: "Avoid spoilers" },
  });
  assert.equal(saved.settings.custom_instructions, "Avoid spoilers");
  assert.equal(
    partnerSettings(saved.settings).custom_instructions,
    "Avoid spoilers",
  );
  assert.equal(sanitizeConfig({}).settings.custom_instructions, "");
});

test("no headphones is a live setting, kept across restarts", () => {
  const saved = partnerSettings({ no_headphones: true });
  assert.equal(saved.no_headphones, true);
  assert.equal(
    sanitizeConfig({ settings: saved }).settings.no_headphones,
    true,
  );
  assert.equal(partnerSettings({}).no_headphones, false);
});

test("the old launch option for no headphones carries over to the setting", () => {
  const config = sanitizeConfig({ tuning: { halfDuplex: true }, settings: {} });
  assert.equal(config.settings.no_headphones, true);
});
