import test from "node:test";
import assert from "node:assert/strict";
import {
  runCandyBatch,
  summarizeCandyResults,
  validateCandySettings,
} from "../../static/candy-test-core.mjs";

test("accepts the inclusive round and timeout boundaries", () => {
  assert.deepEqual(validateCandySettings({ rounds: 1, timeoutSeconds: 30 }), {
    valid: true,
    errors: {},
  });
  assert.deepEqual(validateCandySettings({ rounds: 50, timeoutSeconds: 1800 }), {
    valid: true,
    errors: {},
  });
});

test("rejects out-of-range and non-integer settings", () => {
  for (const rounds of [0, 51, 1.5, "3", true, null]) {
    assert.equal(validateCandySettings({ rounds, timeoutSeconds: 30 }).valid, false, `rounds=${rounds}`);
  }
  for (const timeoutSeconds of [29, 1801, 30.5, "60", false, null]) {
    assert.equal(validateCandySettings({ rounds: 1, timeoutSeconds }).valid, false, `timeoutSeconds=${timeoutSeconds}`);
  }
  assert.deepEqual(validateCandySettings({ rounds: 0, timeoutSeconds: 1801 }).errors, {
    rounds: "rounds must be an integer from 1 to 50",
    timeoutSeconds: "timeoutSeconds must be an integer from 30 to 1800",
  });
});

test("runs probes sequentially once per round and reports immutable progress snapshots", async () => {
  const order = [];
  const snapshots = [];
  const result = await runCandyBatch({
    rounds: 3,
    probe: async ({ round }) => {
      order.push(`start-${round}`);
      await Promise.resolve();
      order.push(`end-${round}`);
      return { round: 99, status: round === 2 ? "incorrect" : "correct", answer: String(round) };
    },
    onUpdate: (snapshot) => snapshots.push(snapshot),
  });

  assert.deepEqual(order, ["start-1", "end-1", "start-2", "end-2", "start-3", "end-3"]);
  assert.deepEqual(result.results, [
    { round: 1, status: "correct", answer: "1" },
    { round: 2, status: "incorrect", answer: "2" },
    { round: 3, status: "correct", answer: "3" },
  ]);
  assert.deepEqual(result.summary, {
    plannedRounds: 3,
    completedRounds: 3,
    counts: { correct: 2, incorrect: 1, ungraded: 0, error: 0, not_run: 0 },
    gradedRounds: 3,
    correctRate: 2 / 3,
  });
  assert.equal(snapshots[0].completedRounds, 0);
  assert.deepEqual(snapshots[0].results, [
    { round: 1, status: "pending" },
    { round: 2, status: "pending" },
    { round: 3, status: "pending" },
  ]);
  assert.deepEqual(
    snapshots.find((snapshot) => snapshot.currentRound === 1 && snapshot.results[0].status === "running")?.results,
    [
      { round: 1, status: "running" },
      { round: 2, status: "pending" },
      { round: 3, status: "pending" },
    ],
  );
  assert.equal(snapshots.at(-1).completedRounds, 3);
  assert.equal(Object.isFrozen(snapshots[0]), true);
  assert.equal(Object.isFrozen(snapshots[0].results), true);
  assert.equal(Object.isFrozen(snapshots.at(-1).results), true);
  assert.equal(Object.isFrozen(snapshots.at(-1).results[0]), true);
  assert.equal(snapshots[0].results[0].status, "pending");
});

test("continues after an error result and a thrown probe failure", async () => {
  const calls = [];
  const replies = [
    { status: "error", answer: null, error: "provider error" },
    new Error("request failed"),
    { status: "ungraded", answer: "not parseable" },
    { status: "not_run" },
  ];
  const result = await runCandyBatch({
    rounds: 4,
    probe: async ({ round }) => {
      calls.push(round);
      const reply = replies.shift();
      if (reply instanceof Error) throw reply;
      return reply;
    },
  });

  assert.deepEqual(calls, [1, 2, 3, 4]);
  assert.deepEqual(result.results, [
    { round: 1, status: "error", answer: null, error: "provider error" },
    { round: 2, status: "error", error: "request failed" },
    { round: 3, status: "ungraded", answer: "not parseable" },
    { round: 4, status: "error", error: "Probe returned an invalid status" },
  ]);
});

test("stops after the current probe and marks untouched rounds not_run", async () => {
  const calls = [];
  const snapshots = [];
  let stop = false;
  const result = await runCandyBatch({
    rounds: 4,
    probe: async ({ round }) => {
      calls.push(round);
      if (round === 2) stop = true;
      return { status: "correct", answer: String(round) };
    },
    shouldStop: () => stop,
    onUpdate: (snapshot) => snapshots.push(snapshot),
  });

  assert.deepEqual(calls, [1, 2]);
  assert.deepEqual(result.results, [
    { round: 1, status: "correct", answer: "1" },
    { round: 2, status: "correct", answer: "2" },
    { round: 3, status: "not_run" },
    { round: 4, status: "not_run" },
  ]);
  assert.equal(snapshots.at(-1).completedRounds, 2);
  assert.equal(snapshots.at(-1).results.length, 4);
  assert.deepEqual(result.summary, {
    plannedRounds: 4,
    completedRounds: 2,
    counts: { correct: 2, incorrect: 0, ungraded: 0, error: 0, not_run: 2 },
    gradedRounds: 2,
    correctRate: 1,
  });
});

test("summarizes statuses and excludes ungraded, error, and not_run from correct rate", () => {
  const results = [
    { round: 1, status: "correct" },
    { round: 2, status: "incorrect" },
    { round: 3, status: "correct" },
    { round: 4, status: "ungraded" },
    { round: 5, status: "error" },
    { round: 6, status: "not_run" },
  ];

  assert.deepEqual(summarizeCandyResults(results, 6), {
    plannedRounds: 6,
    completedRounds: 5,
    counts: { correct: 2, incorrect: 1, ungraded: 1, error: 1, not_run: 1 },
    gradedRounds: 3,
    correctRate: 2 / 3,
  });
  assert.equal(summarizeCandyResults([{ round: 1, status: "error" }], 1).correctRate, null);
  assert.deepEqual(summarizeCandyResults([
    { round: 1, status: "correct" },
    { round: 2, status: "running" },
    { round: 3, status: "pending" },
  ], 3), {
    plannedRounds: 3,
    completedRounds: 1,
    counts: { correct: 1, incorrect: 0, ungraded: 0, error: 0, not_run: 0 },
    gradedRounds: 1,
    correctRate: 1,
  });
});
