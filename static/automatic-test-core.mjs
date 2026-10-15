const PREFERENCES_KEY = "modeltrace.codex-test.preferences";
const REASONING_EFFORTS = new Set(["low", "medium", "high", "xhigh"]);
const TERMINAL_STATES = new Set(["done", "invalid", "error"]);

function normalizedPreferences(preferences = {}) {
  return {
    manualPath: typeof preferences?.manualPath === "string" ? preferences.manualPath : "",
    model: typeof preferences?.model === "string" ? preferences.model : "gpt-6-astra",
    reasoningEffort: REASONING_EFFORTS.has(preferences?.reasoningEffort)
      ? preferences.reasoningEffort
      : "low",
  };
}

export function readCodexPreferences(storage) {
  try {
    const parsed = JSON.parse(storage.getItem(PREFERENCES_KEY));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return normalizedPreferences();
    }
    return normalizedPreferences(parsed);
  } catch {
    return normalizedPreferences();
  }
}

export function writeCodexPreferences(storage, preferences) {
  storage.setItem(PREFERENCES_KEY, JSON.stringify(normalizedPreferences(preferences)));
}

export async function collectAutomaticOutputs({ challenges, configuration, probe, target, onProgress }) {
  const states = challenges.map(() => "pending");
  const outputs = [];
  const errors = [];
  const report = (status) => {
    const snapshot = {
      states: Object.freeze([...states]),
      outputs: Object.freeze(outputs.map((output) => Object.freeze({ ...output }))),
      errors: Object.freeze(errors.map((error) => Object.freeze({ ...error }))),
      status,
    };
    Object.freeze(snapshot);
    onProgress(snapshot);
  };

  report("准备调用模型");
  for (let index = 0; index < challenges.length && outputs.length < target; index += 1) {
    const challenge = challenges[index];
    states[index] = "working";
    report(`正在进行第 ${index + 1} 次尝试，等待模型完整输出……`);

    try {
      const payload = await probe({
        ...configuration,
        prompt: challenge.prompt,
        expected_count: challenge.expected_count,
      });
      if (payload.accepted) {
        outputs.push({ text: payload.text, expected_count: challenge.expected_count });
        states[index] = "done";
      } else {
        errors.push({
          attempt: index + 1,
          message: `有效数字 ${payload.parsed_numbers}/${payload.minimum_numbers}`,
        });
        states[index] = "invalid";
      }
    } catch (error) {
      errors.push({ attempt: index + 1, message: error?.message || String(error) });
      states[index] = "error";
    }
    report(`当前已有 ${outputs.length}/${target} 份有效回答`);
  }

  if (outputs.length === target) {
    states.forEach((state, index) => {
      if (state === "pending") states[index] = "skipped";
    });
  }

  const attempted = states.filter((state) => TERMINAL_STATES.has(state)).length;
  report(outputs.length === target
    ? `测试完成：${outputs.length}/${target} 份有效回答进入归因`
    : `尝试结束：获得 ${outputs.length}/${target} 份有效回答`);

  return { outputs, errors, states, attempted };
}
