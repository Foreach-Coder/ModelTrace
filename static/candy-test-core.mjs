const STATUSES = ["correct", "incorrect", "ungraded", "error", "not_run"];
const PROBE_STATUSES = ["correct", "incorrect", "ungraded", "error"];

export function validateCandySettings({ rounds, timeoutSeconds } = {}) {
  const errors = {};
  if (!Number.isInteger(rounds) || rounds < 1 || rounds > 50) {
    errors.rounds = "rounds must be an integer from 1 to 50";
  }
  if (!Number.isInteger(timeoutSeconds) || timeoutSeconds < 30 || timeoutSeconds > 1800) {
    errors.timeoutSeconds = "timeoutSeconds must be an integer from 30 to 1800";
  }
  return { valid: Object.keys(errors).length === 0, errors };
}

export async function runCandyBatch({ rounds, probe, onUpdate, shouldStop } = {}) {
  const results = Array.from({ length: rounds }, (_, index) => ({ round: index + 1, status: "pending" }));
  const report = (currentRound) => {
    if (typeof onUpdate !== "function") return;
    const snapshot = deepFreeze({
      plannedRounds: rounds,
      completedRounds: results.filter((result) => PROBE_STATUSES.includes(result.status)).length,
      currentRound,
      results: results.map((result) => cloneValue(result)),
    });
    onUpdate(snapshot);
  };

  report(null);
  for (let round = 1; round <= rounds; round += 1) {
    results[round - 1] = { round, status: "running" };
    report(round);
    let result;
    try {
      const response = await probe({ round });
      result = response && typeof response === "object"
        ? { ...response, round }
        : { round, status: "error", error: "Probe returned an invalid result" };
      if (!PROBE_STATUSES.includes(result.status)) {
        result = { round, status: "error", error: "Probe returned an invalid status" };
      }
    } catch (error) {
      result = {
        round,
        status: "error",
        error: error instanceof Error ? error.message : String(error),
      };
    }
    results[round - 1] = result;
    report(round);

    if (typeof shouldStop === "function" && shouldStop()) {
      for (let untouchedRound = round + 1; untouchedRound <= rounds; untouchedRound += 1) {
        results[untouchedRound - 1] = { round: untouchedRound, status: "not_run" };
      }
      if (round < rounds) report(null);
      break;
    }
  }
  return {
    results,
    summary: summarizeCandyResults(results, rounds),
  };
}

export function summarizeCandyResults(results, plannedRounds) {
  const counts = Object.fromEntries(STATUSES.map((status) => [status, 0]));
  for (const result of results) {
    if (result && STATUSES.includes(result.status)) counts[result.status] += 1;
  }
  const gradedRounds = counts.correct + counts.incorrect;
  return {
    plannedRounds,
    completedRounds: results.filter((result) => PROBE_STATUSES.includes(result?.status)).length,
    counts,
    gradedRounds,
    correctRate: gradedRounds === 0 ? null : counts.correct / gradedRounds,
  };
}

function cloneValue(value) {
  if (Array.isArray(value)) return value.map(cloneValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, cloneValue(item)]));
  }
  return value;
}

function deepFreeze(value) {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    for (const item of Object.values(value)) deepFreeze(item);
    Object.freeze(value);
  }
  return value;
}
