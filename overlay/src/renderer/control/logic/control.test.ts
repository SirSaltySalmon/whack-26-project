import assert from "node:assert/strict";
import { test } from "node:test";
import type { KeyList } from "../../../lib/controlBridge.ts";
import type {
  BrainDescription,
  BrainStatus,
  FactView,
} from "../../../lib/protocol.generated.ts";
import type { ControlTab } from "../tabs/types.ts";
import { liveCapabilities, predictCapabilities } from "./capabilities.ts";
import { availableKeys } from "./choices.ts";
import { ago, groupFacts } from "./memory.ts";
import { RequestTracker } from "./requests.ts";
import { pickTab, sortTabs } from "./tabs.ts";

const tab = (id: string, order: number, title = id): ControlTab => ({
  id,
  title,
  order,
  icon: "x",
  Component: () => null,
});

test("tabs sort by order, then title", () => {
  const sorted = sortTabs([
    tab("logs", 90),
    tab("b", 20, "B"),
    tab("a", 20, "A"),
    tab("agent", 10),
  ]);
  assert.deepEqual(
    sorted.map((t) => t.id),
    ["agent", "a", "b", "logs"],
  );
});

test("two tabs with one id are refused", () => {
  assert.throws(
    () => sortTabs([tab("memory", 30), tab("memory", 50)]),
    /memory/,
  );
});

test("the remembered tab is reopened, or the first if it's gone", () => {
  const tabs = sortTabs([tab("agent", 10), tab("memory", 30)]);
  assert.equal(pickTab(tabs, "memory")?.id, "memory");
  assert.equal(pickTab(tabs, "avatar")?.id, "agent");
  assert.equal(pickTab([], null), undefined);
});

test("replies settle the request with the same id", async () => {
  const requests = new RequestTracker(1000);
  const first = requests.open("memory.results");
  const second = requests.open("memory.context");
  assert.notEqual(first.id, second.id);

  assert.equal(
    requests.settle({ type: "memory.context", request_id: second.id }),
    true,
  );
  assert.equal(
    requests.settle({ type: "memory.results", request_id: first.id }),
    true,
  );
  assert.deepEqual(await second.reply, {
    type: "memory.context",
    request_id: second.id,
  });
  assert.deepEqual(await first.reply, {
    type: "memory.results",
    request_id: first.id,
  });
  assert.equal(requests.size, 0);
});

test("errors, unknown ids and pushes are handled", async () => {
  const requests = new RequestTracker(1000);
  const asked = requests.open("memory.results");
  assert.equal(requests.settle({ type: "settings.state" }), false);
  assert.equal(
    requests.settle({ type: "memory.results", request_id: "nope" }),
    false,
  );
  requests.settle({
    type: "control.error",
    request_id: asked.id,
    message: "RuntimeError",
  });
  await assert.rejects(asked.reply, /RuntimeError/);
});

test("requests time out and fail on disconnect", async () => {
  const requests = new RequestTracker(10);
  await assert.rejects(requests.open("memory.results").reply, /in time/);
  const slow = new RequestTracker(1000);
  const waiting = slow.open("memory.results").reply;
  slow.failAll("Disconnected");
  await assert.rejects(waiting, /Disconnected/);
  assert.equal(slow.size, 0);
});

test("capabilities follow the keys, and replay never watches or listens", () => {
  const on = (replay: boolean, ...keys: string[]) =>
    predictCapabilities({
      keys: new Set(keys) as never,
      voiceChosen: true,
      gameTitle: "Terraria",
      replay,
    })
      .filter((c) => c.on)
      .map((c) => c.id);

  assert.deepEqual(on(false), []);
  assert.deepEqual(on(false, "GEMINI_API_KEY"), ["talking", "wiki"]);
  assert.deepEqual(
    on(
      false,
      "ANTHROPIC_API_KEY",
      "DEEPGRAM_API_KEY",
      "ELEVENLABS_API_KEY",
      "GEMINI_API_KEY",
    ),
    ["watching", "listening", "speaking", "talking", "wiki"],
  );
  assert.deepEqual(
    on(true, "ANTHROPIC_API_KEY", "DEEPGRAM_API_KEY", "GEMINI_API_KEY"),
    ["talking"],
  );
});

test("live capabilities come from the brain's status", () => {
  const status: BrainStatus = {
    type: "brain.status",
    mode: "live",
    game_title: "Terraria",
    session_id: 1,
    watching: true,
    listening: false,
    speaking: false,
    talking: true,
    tools: true,
    wiki_url: "https://terraria.wiki.gg/api.php",
  };
  const on = liveCapabilities(status)
    .filter((c) => c.on)
    .map((c) => c.id);
  assert.deepEqual(on, ["watching", "talking", "wiki"]);
});

const fact = (
  id: number,
  attribute: string,
  value: string,
  validTo: number | null,
): FactView => ({
  id,
  subject: "player",
  attribute,
  value,
  source: "player",
  confidence: 0.9,
  tentative: false,
  valid_from: id,
  valid_to: validTo,
});

test("facts group by subject and attribute, with history and conflicts", () => {
  const groups = groupFacts([
    fact(4, "class", "Mage", null),
    fact(3, "Weapon", "Night's Edge", null),
    fact(2, "class", "Summoner", 4),
    fact(1, "class", "Ranger", 2),
    fact(5, "weapon", "Terra Blade", null),
  ]);
  assert.equal(groups.length, 2);
  const [klass, weapon] = groups;
  assert.deepEqual(
    klass?.current.map((f) => f.value),
    ["Mage"],
  );
  assert.deepEqual(
    klass?.past.map((f) => f.value),
    ["Summoner", "Ranger"],
  );
  assert.equal(klass?.conflict, false);
  assert.equal(weapon?.conflict, true);
});

test("ages read naturally", () => {
  const now = 1_000_000_000;
  assert.equal(ago(now / 1000 - 10, now), "just now");
  assert.equal(ago(now / 1000 - 300, now), "5 min ago");
  assert.equal(ago(now / 1000 - 7200, now), "2 h ago");
});

test("keys count as available when saved here or set in the brain's .env", () => {
  const keys = {
    keys: [
      { name: "DEEPGRAM_API_KEY", saved: true },
      { name: "GEMINI_API_KEY", saved: false },
    ],
    canEncrypt: true,
  } as unknown as KeyList; // Only the fields availableKeys reads
  const description = {
    keys_set: { ANTHROPIC_API_KEY: true, GEMINI_API_KEY: false },
  } as unknown as BrainDescription; // Likewise
  assert.deepEqual([...availableKeys(keys, description)].sort(), [
    "ANTHROPIC_API_KEY",
    "DEEPGRAM_API_KEY",
  ]);
});
