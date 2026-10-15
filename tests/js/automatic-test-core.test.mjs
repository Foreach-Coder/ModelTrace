import test from "node:test";
import assert from "node:assert/strict";
import {
  collectAutomaticOutputs,
  readCodexPreferences,
  writeCodexPreferences,
} from "../../static/automatic-test-core.mjs";

const challenges = Array.from({ length: 6 }, (_, index) => ({
  prompt: `prompt-${index + 1}`,
  expected_count: 100 + index,
}));

test("stops after three accepted outputs and marks remaining attempts skipped", async () => {
  let calls = 0;
  const snapshots = [];
  const result = await collectAutomaticOutputs({
    challenges,
    configuration: { model: "gpt-6-astra" },
    target: 3,
    probe: async () => {
      calls += 1;
      return { accepted: true, text: `answer-${calls}`, parsed_numbers: 100, minimum_numbers: 80 };
    },
    onProgress: (snapshot) => snapshots.push(snapshot),
  });
  assert.equal(calls, 3);
  assert.deepEqual(result.states, ["done", "done", "done", "skipped", "skipped", "skipped"]);
  assert.equal(result.outputs.length, 3);
  assert.equal(result.attempted, 3);
  assert.deepEqual(snapshots[0].states, ["pending", "pending", "pending", "pending", "pending", "pending"]);
  assert.deepEqual(snapshots.at(-1).states, ["done", "done", "done", "skipped", "skipped", "skipped"]);
  assert.equal(snapshots[0].status, "准备调用模型");
  assert.equal(Object.isFrozen(snapshots.at(-1)), true);
  assert.equal(Object.isFrozen(snapshots.at(-1).states), true);
  assert.equal(Object.isFrozen(snapshots.at(-1).outputs), true);
  assert.equal(Object.isFrozen(snapshots.at(-1).outputs[0]), true);
  assert.equal(Object.isFrozen(snapshots.at(-1).errors), true);
  assert.deepEqual(snapshots.at(-1).outputs, [
    { text: "answer-1", expected_count: 100 },
    { text: "answer-2", expected_count: 101 },
    { text: "answer-3", expected_count: 102 },
  ]);
  assert.deepEqual(snapshots[0].states, ["pending", "pending", "pending", "pending", "pending", "pending"]);
});

test("continues after invalid output and rejected probe", async () => {
  const replies = [
    { accepted: false, text: "short", parsed_numbers: 12, minimum_numbers: 80 },
    new Error("CLI failed"),
    { accepted: true, text: "valid", parsed_numbers: 80, minimum_numbers: 80 },
  ];
  const snapshots = [];
  const result = await collectAutomaticOutputs({
    challenges: challenges.slice(0, 3),
    configuration: {},
    target: 3,
    probe: async () => {
      const reply = replies.shift();
      if (reply instanceof Error) throw reply;
      return reply;
    },
    onProgress: (snapshot) => snapshots.push(snapshot),
  });
  assert.deepEqual(result.states, ["invalid", "error", "done"]);
  assert.deepEqual(result.errors, [
    { attempt: 1, message: "有效数字 12/80" },
    { attempt: 2, message: "CLI failed" },
  ]);
  assert.deepEqual(result.outputs, [{ text: "valid", expected_count: 102 }]);
  assert.equal(result.attempted, 3);
  assert.equal(Object.isFrozen(snapshots.at(-1).errors), true);
  assert.equal(Object.isFrozen(snapshots.at(-1).errors[0]), true);
});

test("returns zero outputs after all six probes fail", async () => {
  const result = await collectAutomaticOutputs({
    challenges,
    configuration: {},
    target: 3,
    probe: async () => { throw new Error("unavailable"); },
    onProgress: () => {},
  });
  assert.equal(result.outputs.length, 0);
  assert.deepEqual(result.errors, challenges.map((_, index) => ({
    attempt: index + 1,
    message: "unavailable",
  })));
  assert.equal(result.attempted, 6);
});

test("passes transport configuration and challenge fields to each probe", async () => {
  const seen = [];
  await collectAutomaticOutputs({
    challenges: [challenges[0]],
    configuration: { codex_path: "C:\\Codex\\codex.exe", model: "gpt-6-astra" },
    target: 3,
    probe: async (payload) => {
      seen.push(payload);
      return { accepted: false, text: "", parsed_numbers: 0, minimum_numbers: 80 };
    },
    onProgress: () => {},
  });
  assert.deepEqual(seen, [{
    codex_path: "C:\\Codex\\codex.exe",
    model: "gpt-6-astra",
    prompt: "prompt-1",
    expected_count: 100,
  }]);
});

test("Codex preferences default safely when storage is empty or malformed", () => {
  const emptyStorage = { getItem: () => null };
  assert.deepEqual(readCodexPreferences(emptyStorage), {
    manualPath: "",
    model: "gpt-6-astra",
    reasoningEffort: "low",
    useUserConfig: false,
  });
  const malformedStorage = { getItem: () => "not-json" };
  assert.deepEqual(readCodexPreferences(malformedStorage), {
    manualPath: "",
    model: "gpt-6-astra",
    reasoningEffort: "low",
    useUserConfig: false,
  });
  const wrongTypedStorage = { getItem: () => JSON.stringify({ manualPath: "C:\\Codex", model: 12, reasoningEffort: "ultra", useUserConfig: "true" }) };
  assert.deepEqual(readCodexPreferences(wrongTypedStorage), {
    manualPath: "C:\\Codex",
    model: "gpt-6-astra",
    reasoningEffort: "low",
    useUserConfig: false,
  });
});

test("Codex preferences persist only the manual override supplied by the UI", () => {
  let saved = null;
  const storage = { setItem: (key, value) => { saved = { key, value }; } };
  writeCodexPreferences(storage, {
    manualPath: "",
    model: "gpt-6-astra",
    reasoningEffort: "medium",
    useUserConfig: true,
    authenticated: true,
    pathSource: "desktop",
  });
  assert.equal(saved.key, "modeltrace.codex-test.preferences");
  assert.deepEqual(JSON.parse(saved.value), {
    manualPath: "",
    model: "gpt-6-astra",
    reasoningEffort: "medium",
    useUserConfig: true,
  });
});
