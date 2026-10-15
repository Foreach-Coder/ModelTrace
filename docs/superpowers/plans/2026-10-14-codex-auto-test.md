# Codex Automatic Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Windows-only “Codex 自动测试” workflow that discovers the desktop `codex.exe`, executes isolated `codex exec` probes, and reuses ModelTrace’s existing challenge validation and fingerprint attribution flow.

**Architecture:** Extract probe-output acceptance into a transport-neutral Python module, then add an isolated Windows Codex runtime adapter and a Flask Blueprint for status/probe endpoints. Extract the browser’s six-attempt/three-valid collection loop into a tested JavaScript module so API and Codex tabs share orchestration while keeping transport-specific forms and requests.

**Tech Stack:** Python 3, Flask, Python `unittest`, Windows `subprocess`, browser JavaScript ES modules, Node.js built-in test runner, HTML/CSS.

**Spec:** `docs/superpowers/specs/2026-10-14-codex-auto-test-design.md`

## Global Constraints

- Work directly in `D:\Develop\DevEnv\ModelTrace` on branch `dev-foreach`; the user explicitly prohibited worktrees.
- Preserve the user’s existing unstaged/untracked DeepSeek files. Never stage or modify `data/unified_bank.json`, `data/custom_banks.json`, `data/deepseek_bank.json`, or `data/deepseek_reference.jsonl`.
- The first release supports Windows only.
- The model default is exactly `gpt-6-astra`; reasoning defaults to exactly `low` and permits only `low`, `medium`, `high`, and `xhigh`.
- Each Codex probe has a 120-second timeout, uses an ephemeral session and read-only sandbox, ignores user configuration, and receives the challenge through stdin.
- Runtime discovery priority is: valid manual path, `MODELTRACE_CODEX_PATH`, newest desktop-bundled `%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe`, `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe`, then Windows `PATH`.
- Automatic testing keeps the existing target of 3 valid outputs from at most 6 sequential attempts and permits analysis when at least 1 output is valid.
- Automatic discovery must place the resolved full `codex.exe` path in the visible input. Persist only a user-supplied successful path as a manual override; do not persist an automatically discovered path as a manual override.
- Do not expose arbitrary CLI arguments, use a shell, expose authentication data, or return full internal logs to the browser.
- Add no production dependency; Python tests use `unittest` and JavaScript tests use `node --test`.
- Do not modify fingerprint algorithms, challenge contents, reference data, or generated bank files.
- Every production behavior follows strict TDD: add the focused test, run it and observe the expected failure, implement the minimum, then rerun the focused and relevant regression suites.

---

### Task 1: Share probe-output acceptance between transports

**Files:**
- Create: `automatic_testing.py`
- Create: `tests/__init__.py`
- Create: `tests/test_automatic_testing.py`
- Create: `tests/test_api_probe.py`
- Modify: `app.py:1-15,203-228`

**Interfaces:**
- Consumes: `fingerprint.parse_numbers(text: str) -> list[int]`.
- Produces: `evaluate_probe(text: str, expected_count: int) -> dict[str, object]` with exactly `text`, `parsed_numbers`, `minimum_numbers`, and `accepted` keys.
- Preserves: `POST /api/test/probe` response shape and HTTP behavior for valid requests.

- [ ] **Step 1: Add focused tests for acceptance and route compatibility**

Create `tests/test_automatic_testing.py`:

```python
import unittest

from automatic_testing import evaluate_probe


class EvaluateProbeTests(unittest.TestCase):
    def test_accepts_output_at_minimum_number_threshold(self):
        text = ", ".join(str(number) for number in range(80))

        self.assertEqual(
            evaluate_probe(text, 100),
            {
                "text": text,
                "parsed_numbers": 80,
                "minimum_numbers": 80,
                "accepted": True,
            },
        )

    def test_rejects_output_below_minimum_number_threshold(self):
        text = ", ".join(str(number) for number in range(79))

        result = evaluate_probe(text, 100)

        self.assertEqual(result["parsed_numbers"], 79)
        self.assertEqual(result["minimum_numbers"], 80)
        self.assertFalse(result["accepted"])

    def test_rejects_non_positive_expected_count(self):
        with self.assertRaisesRegex(ValueError, "expected_count"):
            evaluate_probe("1, 2, 3", 0)


if __name__ == "__main__":
    unittest.main()
```

Create `tests/test_api_probe.py` using Flask’s real test client and mocking only the external model call:

```python
import unittest
from unittest.mock import patch

from app import app


class ApiProbeRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch("app.request_completion")
    def test_api_probe_keeps_existing_response_contract(self, request_completion):
        text = ", ".join(str(number) for number in range(80))
        request_completion.return_value = text

        response = self.client.post(
            "/api/test/probe",
            json={
                "base_url": "https://example.test/v1",
                "api_key": "secret",
                "api_model": "model",
                "temperature": None,
                "prompt": "generate",
                "expected_count": 100,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "text": text,
                "parsed_numbers": 80,
                "minimum_numbers": 80,
                "accepted": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_automatic_testing tests.test_api_probe -v
```

Expected: `tests.test_automatic_testing` fails to import because `automatic_testing.py` does not exist. This is the intended feature-missing failure; resolve no production code before observing it.

- [ ] **Step 3: Implement the transport-neutral evaluator**

Create `automatic_testing.py` with this public behavior:

```python
from __future__ import annotations

import math

from fingerprint import parse_numbers


def evaluate_probe(text: str, expected_count: int) -> dict[str, object]:
    if expected_count <= 0:
        raise ValueError("expected_count 必须是正整数")
    parsed_numbers = len(parse_numbers(text))
    minimum_numbers = max(80, math.ceil(expected_count * 0.55))
    return {
        "text": text,
        "parsed_numbers": parsed_numbers,
        "minimum_numbers": minimum_numbers,
        "accepted": parsed_numbers >= minimum_numbers,
    }
```

Modify `app.py` to import `evaluate_probe`, remove the now-unused `math`/`parse_numbers` imports, and return `jsonify(evaluate_probe(text, int(payload["expected_count"])))` from the existing API probe.

- [ ] **Step 4: Run focused and regression tests and verify GREEN**

Run:

```powershell
python -m unittest tests.test_automatic_testing tests.test_api_probe -v
python -m unittest discover -s tests -v
```

Expected: all tests pass with no warnings or tracebacks.

- [ ] **Step 5: Commit only Task 1 files**

```powershell
git add -- automatic_testing.py tests/__init__.py tests/test_automatic_testing.py tests/test_api_probe.py app.py
git diff --cached --check
git commit -m "refactor: share automatic probe evaluation"
```

---

### Task 2: Discover and execute the Windows Codex CLI safely

**Files:**
- Create: `codex_runner.py`
- Create: `tests/test_codex_runner.py`

**Interfaces:**
- Produces: immutable `CodexRuntime(path: str, source: str, version: str)`.
- Produces: `discover_codex(explicit_path: str = "") -> CodexRuntime`.
- Produces: `get_codex_status(explicit_path: str = "") -> dict[str, object]`.
- Produces: `request_codex_completion(codex_path: str, model: str, reasoning_effort: str, prompt: str, timeout: int = 120) -> str`.
- Produces typed exceptions `CodexUnavailableError`, `CodexAuthenticationError`, and `CodexExecutionError` for HTTP mapping in Task 3.

- [ ] **Step 1: Add discovery tests**

Create `tests/test_codex_runner.py` with `TemporaryDirectory` fake `codex.exe` files and dependency patches. Use a `version_result(version)` helper that returns a complete `subprocess.CompletedProcess`. Implement these independently named cases with the stated fixtures and literal expectations:

| Test | Fixture | Expected result |
|---|---|---|
| `test_explicit_path_wins_over_all_automatic_candidates` | A valid explicit executable plus valid environment and desktop executables | The resolved explicit absolute path, source `manual`, and its version |
| `test_environment_path_wins_when_no_explicit_path_is_given` | `MODELTRACE_CODEX_PATH` points to a valid executable while a desktop executable also exists | Environment absolute path and source `environment` |
| `test_newest_valid_desktop_cli_is_selected` | Two desktop candidates return `0.138.0` and `0.162.0-alpha.17.2` | The `0.162.0-alpha.17.2` candidate and source `desktop` |
| `test_program_install_precedes_path_lookup` | A valid Programs install plus a different `shutil.which` result | Programs install path and source `install` |
| `test_invalid_explicit_path_does_not_fall_back` | Missing explicit path plus a valid desktop candidate | `CodexUnavailableError` mentioning the explicit path |
| `test_non_windows_platform_is_reported_as_unavailable` | Patch the module platform predicate false | `CodexUnavailableError` containing `Windows` |

Patch the process boundary (`subprocess.run`) so fake `--version` calls return complete `subprocess.CompletedProcess` objects such as:

```python
subprocess.CompletedProcess(args=[], returncode=0, stdout="codex-cli 0.162.0-alpha.17.2\n", stderr="")
```

Assertions must check the returned runtime path, source (`manual`, `environment`, `desktop`, `install`, or `path`), and parsed version. The “newest” test must provide both `0.138.0` and `0.162.0-alpha.17.2` and expect the latter.

- [ ] **Step 2: Run discovery tests and verify RED**

Run:

```powershell
python -m unittest tests.test_codex_runner.CodexDiscoveryTests -v
```

Expected: import failure because `codex_runner.py` does not exist.

- [ ] **Step 3: Implement discovery and version ordering**

Implement the public dataclass/exceptions and discovery order from Global Constraints. Keep subprocess calls as argument lists with `shell=False`. Use a private semantic key whose stable-release flag sorts a stable release after its prerelease:

```python
def _version_key(version: str) -> tuple[int, int, int, int, tuple[int, ...]]:
    match = re.fullmatch(
        r"(\d+)\.(\d+)\.(\d+)(?:-([a-z]+)(?:\.(\d+(?:\.\d+)*))?)?",
        version,
        flags=re.IGNORECASE,
    )
    if match is None:
        return (0, 0, 0, -1, ())
    prerelease_numbers = tuple(
        int(part) for part in (match.group(5) or "").split(".") if part
    )
    stable = 1 if match.group(4) is None else 0
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        stable,
        prerelease_numbers,
    )
```

An explicit path must exist, be a regular file named `codex.exe` case-insensitively, and pass `--version`; otherwise raise `CodexUnavailableError` without falling back. Invalid automatic candidates are skipped so a stale environment/install entry does not hide a working desktop or PATH candidate.

- [ ] **Step 4: Add status tests and verify RED**

Add cases that make the real `get_codex_status` orchestration exercise discovery and the `codex login status` boundary:

| Test | Login/discovery result | Assertions |
|---|---|---|
| `test_status_reports_resolved_path_source_version_and_authentication` | Valid manual executable; login returns code 0 | Exact success dictionary below |
| `test_status_reports_cli_that_is_present_but_not_authenticated` | Discovery succeeds; login returns code 1 and `Not logged in` | `available=True`, `authenticated=False`, known path/source/version retained, Chinese `error` present |
| `test_status_returns_structured_unavailable_result` | Discovery raises `CodexUnavailableError("未找到 codex.exe")` | `available=False`, `authenticated=False`, empty path/version, and exact error text |

The successful literal response must be:

```python
{
    "available": True,
    "authenticated": True,
    "path": str(executable.resolve()),
    "source": "manual",
    "version": "0.162.0-alpha.17.2",
}
```

Run:

```powershell
python -m unittest tests.test_codex_runner.CodexStatusTests -v
```

Expected: failures because status/authentication behavior is not implemented.

- [ ] **Step 5: Implement structured status inspection**

Execute `[runtime.path, "login", "status"]` with a short timeout. Return the successful structure above when the command exits zero. For unauthenticated or unavailable results, return the same non-secret fields that are known plus `available`, `authenticated`, and a concise Chinese `error`; never include raw stdout/stderr beyond a sanitized 300-character diagnostic.

- [ ] **Step 6: Add execution and validation tests and verify RED**

Add focused cases with these concrete mutations and observable results:

| Test | Process fixture | Observable assertion |
|---|---|---|
| `test_exec_uses_fixed_safe_arguments_and_sends_prompt_on_stdin` | Authenticated runtime and successful fake process | Recorded argument list exactly matches Step 7; `communicate` receives `"challenge"` and timeout `120`; `shell` is `False` |
| `test_exec_reads_and_returns_output_last_message` | Fake writes `"1, 2, 3\n"` to the requested output file | Public return value is `"1, 2, 3"` |
| `test_exec_rejects_unknown_reasoning_effort_before_starting_process` | Effort `ultra` | `ValueError` and fake `Popen` invocation count remains zero |
| `test_exec_rejects_empty_or_invalid_model_identifier` | Models `""` and `"model --danger"` in subtests | `ValueError` for each and fake `Popen` invocation count remains zero |
| `test_exec_maps_missing_login_to_authentication_error` | Login status exits 1 | `CodexAuthenticationError`; fake `Popen` invocation count remains zero |
| `test_exec_maps_nonzero_exit_to_sanitized_execution_error` | Process exits 1 with a 500-character stderr string | `CodexExecutionError`; message length is bounded and does not contain characters after the 300-character sanitized diagnostic |
| `test_exec_timeout_terminates_process_tree_and_removes_temporary_output` | `communicate` raises `subprocess.TimeoutExpired` with pid `4321` | `CodexExecutionError` mentions 120 seconds; `taskkill` receives `/PID 4321 /T /F`; captured output path no longer exists |
| `test_exec_success_removes_temporary_output` | Successful process writes a non-empty answer | Returned answer is correct and captured output path no longer exists |

Use a purpose-built fake `Popen` that records the argument list and `communicate(input=prompt, timeout=120)`, and writes a fixture answer to the path following `--output-last-message`. Mock only process creation, login/version calls, and `taskkill`; assert the real `request_codex_completion` return value and cleanup behavior.

Run:

```powershell
python -m unittest tests.test_codex_runner.CodexExecutionTests -v
```

Expected: failures because execution has not been implemented.

- [ ] **Step 7: Implement isolated Codex execution**

Build this exact argument contract as a list:

```python
[
    runtime.path,
    "exec",
    "--ignore-user-config",
    "--model", model,
    "-c", f'model_reasoning_effort="{reasoning_effort}"',
    "--ephemeral",
    "--sandbox", "read-only",
    "--skip-git-repo-check",
    "--output-last-message", output_path,
    "-",
]
```

Validate model identifiers with a conservative allowlist that permits letters, numbers, `.`, `_`, `-`, `/`, and `:` and limits them to 128 characters. Validate reasoning effort against the four allowed values. Call `subprocess.Popen` with the argument list followed by `shell=False`, `stdin=subprocess.PIPE`, `stdout=subprocess.PIPE`, `stderr=subprocess.PIPE`, `text=True`, `encoding="utf-8"`, and `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP`; then call `communicate(input=prompt, timeout=timeout)`.

On timeout invoke Windows `taskkill /PID <integer pid> /T /F` as an argument list with `shell=False`, then call `kill()` as a fallback. Always unlink the temporary output file in `finally`. Return the trimmed output file content; treat a missing/empty file or nonzero exit as `CodexExecutionError` with a concise sanitized message.

- [ ] **Step 8: Run Task 2 and regression tests and verify GREEN**

Run:

```powershell
python -m unittest tests.test_codex_runner -v
python -m unittest discover -s tests -v
```

Expected: all tests pass; no real Codex process starts during unit tests.

- [ ] **Step 9: Commit only Task 2 files**

```powershell
git add -- codex_runner.py tests/test_codex_runner.py
git diff --cached --check
git commit -m "feat: add Windows Codex runtime adapter"
```

---

### Task 3: Expose Codex status and probe endpoints

**Files:**
- Create: `codex_routes.py`
- Create: `tests/test_codex_routes.py`
- Modify: `app.py:8-18,150-170`

**Interfaces:**
- Consumes: `get_codex_status`, `request_codex_completion`, the three Codex exception classes, and `evaluate_probe`.
- Produces: Flask `codex_blueprint` with `POST /api/codex/status` and `POST /api/test/codex/probe`.
- `POST /api/codex/status` returns a structured status body with HTTP 200, including unavailable/unauthenticated states.
- `POST /api/test/codex/probe` returns 200 for a completed probe, 400 for invalid input, 503 for unavailable/authentication failures, and 502 for execution/timeout failures.

- [ ] **Step 1: Add endpoint tests**

Create a small real Flask test application in `tests/test_codex_routes.py`, register `codex_blueprint`, and patch only the external runtime boundary. Implement these concrete cases:

| Test | Request/runtime fixture | Expected response |
|---|---|---|
| `test_status_returns_resolved_runtime_details` | POST an empty JSON object; status function returns the complete successful status structure from Task 2 | HTTP 200 and exact status JSON |
| `test_status_returns_unavailable_details_without_hiding_error` | Status returns `available=False` with `error="未找到 codex.exe"` | HTTP 200 and the same error field |
| `test_probe_returns_shared_acceptance_contract` | Valid payload; completion returns exactly 80 comma-separated integers | HTTP 200 and exact evaluator response with `parsed_numbers=80`, `minimum_numbers=80`, `accepted=True` |
| `test_probe_rejects_missing_model_with_400` | Valid payload minus `model` | HTTP 400 and non-empty `error`; completion not invoked |
| `test_probe_rejects_unknown_reasoning_effort_with_400` | Effort `ultra` | HTTP 400 and non-empty `error`; completion not invoked |
| `test_probe_maps_unavailable_and_authentication_errors_to_503` | Two subtests raising the corresponding typed exceptions | HTTP 503 and the exception message in `error` |
| `test_probe_maps_execution_error_to_502` | Completion raises `CodexExecutionError("Codex CLI 执行失败")` | HTTP 502 and exact error JSON |

For the successful probe, return a literal 80-number answer from the patched external completion call and assert the complete real JSON response from `evaluate_probe`.

- [ ] **Step 2: Run endpoint tests and verify RED**

Run:

```powershell
python -m unittest tests.test_codex_routes -v
```

Expected: import failure because `codex_routes.py` does not exist.

- [ ] **Step 3: Implement the Blueprint and validation**

Define `codex_blueprint = Blueprint("codex", __name__)`. Treat an absent JSON body as `{}` for status and as invalid for probe. Normalize an optional `codex_path` with `.strip()`. Validate required `model`, `prompt`, positive integer `expected_count`, and the four allowed efforts before invoking the runtime. Return only `str(error)` in error JSON.

Register the Blueprint once in `app.py` after app construction:

```python
from codex_routes import codex_blueprint

app = Flask(__name__)
app.register_blueprint(codex_blueprint)
```

- [ ] **Step 4: Add an application-registration regression test and verify GREEN**

Add a case using the real `app.test_client()` that patches `codex_routes.get_codex_status`, posts to `/api/codex/status`, and asserts HTTP 200 plus the returned path. This catches a future removal of Blueprint registration.

Run:

```powershell
python -m unittest tests.test_codex_routes -v
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit only Task 3 files**

```powershell
git add -- codex_routes.py tests/test_codex_routes.py app.py
git diff --cached --check
git commit -m "feat: expose Codex automatic test endpoints"
```

---

### Task 4: Extract the shared browser automatic-test runner

**Files:**
- Create: `static/automatic-test-core.mjs`
- Create: `tests/js/automatic-test-core.test.mjs`

**Interfaces:**
- Produces: `collectAutomaticOutputs({ challenges, configuration, probe, target, onProgress }) -> Promise<{outputs, errors, states, attempted}>`.
- Produces: `readCodexPreferences(storage) -> {manualPath, model, reasoningEffort}` and `writeCodexPreferences(storage, preferences)` using key `modeltrace.codex-test.preferences`.
- `probe(configurationWithPromptAndExpectedCount)` resolves to the parsed HTTP payload or rejects with a user-facing `Error`.
- `onProgress(snapshot)` receives immutable snapshots containing `states`, `outputs`, `errors`, and `status`.
- Task 5 imports this function from `static/app.js` for both API and Codex transports.

- [ ] **Step 1: Add Node tests for the shared collection loop**

Create `tests/js/automatic-test-core.test.mjs` with Node’s built-in `node:test` and `node:assert/strict`. Use this fixture and implement the six tests against literal outcomes:

```javascript
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
  const result = await collectAutomaticOutputs({
    challenges,
    configuration: { model: "gpt-6-astra" },
    target: 3,
    probe: async () => {
      calls += 1;
      return { accepted: true, text: `answer-${calls}`, parsed_numbers: 100, minimum_numbers: 80 };
    },
    onProgress: () => {},
  });
  assert.equal(calls, 3);
  assert.deepEqual(result.states, ["done", "done", "done", "skipped", "skipped", "skipped"]);
  assert.equal(result.outputs.length, 3);
  assert.equal(result.attempted, 3);
});

test("continues after invalid output and rejected probe", async () => {
  const replies = [
    { accepted: false, text: "short", parsed_numbers: 12, minimum_numbers: 80 },
    new Error("CLI failed"),
    { accepted: true, text: "valid", parsed_numbers: 80, minimum_numbers: 80 },
  ];
  const result = await collectAutomaticOutputs({
    challenges: challenges.slice(0, 3),
    configuration: {},
    target: 3,
    probe: async () => {
      const reply = replies.shift();
      if (reply instanceof Error) throw reply;
      return reply;
    },
    onProgress: () => {},
  });
  assert.deepEqual(result.states, ["invalid", "error", "done"]);
  assert.deepEqual(result.errors, ["有效数字 12/80", "CLI failed"]);
  assert.equal(result.outputs.length, 1);
  assert.equal(result.attempted, 3);
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
  assert.equal(result.errors.length, 6);
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
  });
  const malformedStorage = { getItem: () => "not-json" };
  assert.deepEqual(readCodexPreferences(malformedStorage), {
    manualPath: "",
    model: "gpt-6-astra",
    reasoningEffort: "low",
  });
});

test("Codex preferences persist only the manual override supplied by the UI", () => {
  let saved = null;
  const storage = { setItem: (key, value) => { saved = { key, value }; } };
  writeCodexPreferences(storage, {
    manualPath: "",
    model: "gpt-6-astra",
    reasoningEffort: "medium",
  });
  assert.equal(saved.key, "modeltrace.codex-test.preferences");
  assert.deepEqual(JSON.parse(saved.value), {
    manualPath: "",
    model: "gpt-6-astra",
    reasoningEffort: "medium",
  });
});
```

For the first case, provide six challenges and a probe that returns `{accepted: true, text: "answer", parsed_numbers: 100, minimum_numbers: 80}`. Assert exactly three probe invocations and states `['done', 'done', 'done', 'skipped', 'skipped', 'skipped']`.

- [ ] **Step 2: Run the Node test and verify RED**

Run:

```powershell
node --test tests/js/automatic-test-core.test.mjs
```

Expected: module-not-found failure for `static/automatic-test-core.mjs`.

- [ ] **Step 3: Implement the transport-neutral collection loop**

Implement the loop with these state transitions:

```javascript
pending -> working -> done
pending -> working -> invalid
pending -> working -> error
pending -> skipped  // only after target reached
```

Use copies when calling `onProgress` so rendering cannot mutate runner state. An invalid response adds `有效数字 <parsed>/<minimum>` to errors; a rejected probe adds its message. Stop once `outputs.length === target`. Compute `attempted` from terminal states rather than from output/error counts.

Implement `readCodexPreferences` so missing, malformed, or wrong-typed stored JSON returns `{manualPath: "", model: "gpt-6-astra", reasoningEffort: "low"}` with individually valid string fields retained when possible and invalid reasoning values reset to `low`. Implement `writeCodexPreferences` by serializing exactly the three normalized fields under `modeltrace.codex-test.preferences`; the UI passes an empty `manualPath` for automatic mode.

- [ ] **Step 4: Run JavaScript tests and verify GREEN**

Run:

```powershell
node --test tests/js/automatic-test-core.test.mjs
node --check static/automatic-test-core.mjs
```

Expected: six tests pass and syntax validation succeeds.

- [ ] **Step 5: Commit only Task 4 files**

```powershell
git add -- static/automatic-test-core.mjs tests/js/automatic-test-core.test.mjs
git diff --cached --check
git commit -m "refactor: share browser automatic test runner"
```

---

### Task 5: Add the Codex tab and integrate both transports

**Files:**
- Create: `tests/test_test_page.py`
- Modify: `templates/index.html:34-66,102-104`
- Modify: `static/app.js:1-225,322-336`
- Modify: `static/styles.css`
- Modify: `README.md:18-25,57-65`

**Interfaces:**
- Consumes: `collectAutomaticOutputs` from Task 4 and the two endpoints from Task 3.
- Produces: a third test mode `data-test-mode="codex"` with panel `id="test-codex"`.
- Produces DOM ids: `codex-test-form`, `codex-path`, `codex-model`, `codex-reasoning-effort`, `codex-detect`, `codex-runtime-status`, `codex-test-progress`, `codex-progress-status`, `codex-progress-count`, `codex-progress-fill`, and `codex-progress-steps`.
- Preserves the existing manual and API test behavior and result structure.

- [ ] **Step 1: Add rendered-page contract tests**

Create `tests/test_test_page.py` using the real Flask client. Parse no source files; assert the user-visible rendered response:

```python
import unittest

from app import app


class TestPageTests(unittest.TestCase):
    def test_model_test_page_offers_codex_automatic_testing(self):
        html = app.test_client().get("/").get_data(as_text=True)

        self.assertIn('data-test-mode="codex"', html)
        self.assertIn('id="test-codex"', html)
        self.assertIn('id="codex-path"', html)
        self.assertIn('value="gpt-6-astra"', html)
        self.assertIn('<option value="low" selected>', html)

    def test_model_test_page_loads_the_automatic_test_module(self):
        html = app.test_client().get("/").get_data(as_text=True)

        self.assertIn('type="module"', html)
        self.assertIn('app.js', html)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the rendered-page tests and verify RED**

Run:

```powershell
python -m unittest tests.test_test_page -v
```

Expected: the Codex-tab assertions fail because the rendered page still has only manual and API modes.

- [ ] **Step 3: Add the third tab, Codex form, status, and progress panel**

Update `templates/index.html` with the exact ids in Interfaces. The path field starts empty with an automatic-detection placeholder. Use a text input, not a browser file input, because browser file inputs do not reveal a usable server-side executable path. Add model value `gpt-6-astra`, a reasoning select with `low` selected, and a separate progress panel matching the existing API visual structure. Load `app.js` with `type="module"`.

Add only minimal CSS needed for a three-tab layout and runtime status states (`working`, `success`, `error`) while reusing existing form, progress, and message classes.

- [ ] **Step 4: Replace API-only orchestration with the tested shared runner**

At the top of `static/app.js` import:

```javascript
import {
  collectAutomaticOutputs,
  readCodexPreferences,
  writeCodexPreferences,
} from "./automatic-test-core.mjs";
```

Replace `renderApiProgress` with a renderer that accepts a set of DOM ids, and replace `testViaApi` with a generic function whose options supply the form, endpoint, configuration, progress ids, and transport label. Keep challenge loading and `/api/analyze` in the UI integration layer; pass only the six challenges and a transport-specific `probe` callback into `collectAutomaticOutputs`.

API submits to `/api/test/probe` with its existing configuration. Codex submits to `/api/test/codex/probe` with:

```javascript
{
  codex_path: byId("codex-path").value.trim(),
  model: byId("codex-model").value.trim(),
  reasoning_effort: byId("codex-reasoning-effort").value,
}
```

Attach result metadata as a transport-neutral object:

```javascript
result.automatic_test = {
  transport: "API" /* or "Codex CLI" */,
  requested: 3,
  attempted,
  max_attempts: challenges.length,
  received: outputs.length,
  errors,
};
```

Update `renderResult` to prefer `automatic_test` while still accepting existing `api_test` data for compatibility.

- [ ] **Step 5: Implement runtime detection, visible path fill, and local persistence**

On initial Codex-tab activation, load preferences through `readCodexPreferences(window.localStorage)`. If a successful manual override is stored, post that path to `/api/codex/status`; otherwise post `{codex_path: ""}` for automatic discovery. On success:

```javascript
byId("codex-path").value = status.path;
```

Render the source, version, and login state alongside the field. The “自动检测” button always posts an empty path, overwrites the visible field with the newly resolved path, and marks the path’s in-memory source as automatic.

Track whether the user edits the path after automatic fill. Persist through `writeCodexPreferences(window.localStorage)` after successful use. Persist `model` and `reasoning_effort` in both modes, but set `manualPath` only when the successful status/test used a user-edited path. The “自动检测” action writes an empty `manualPath`, so an automatically discovered path is visible for the current page but is never persisted as a manual override. Never store authentication output.

- [ ] **Step 6: Update user documentation**

In `README.md`, add “Codex 自动测试” to usage and describe Windows-only behavior, automatic desktop CLI discovery, visible resolved path, optional manual path, current Codex login reuse, default model/reasoning, and the six-attempt/three-valid rule. Add `codex_runner.py`, `codex_routes.py`, and `automatic_testing.py` to the repository structure section.

- [ ] **Step 7: Run focused and complete automated verification**

Run:

```powershell
python -m unittest tests.test_test_page -v
node --test tests/js/automatic-test-core.test.mjs
node --check static/app.js
python -m unittest discover -s tests -v
```

Expected: all Python and JavaScript tests pass and both JavaScript files pass syntax validation.

- [ ] **Step 8: Run the Windows live smoke test**

Start from `get_codex_status("")` and confirm it selects a desktop-bundled executable, reports its full path/version/authentication, and does not select an older PATH copy. Then call `request_codex_completion` with one real `generate_challenges(1)[0]` prompt, `model="gpt-6-astra"`, `reasoning_effort="low"`, and `timeout=120`; pass the text through `evaluate_probe` and confirm it returns a non-empty answer plus a concrete parsed count/threshold result.

This is a live acceptance smoke test, not a default unit test, because it consumes the signed-in Codex account and depends on external service availability. Record the exact executable/version, elapsed time, exit outcome, parsed count, threshold, and accepted value in the task report without recording authentication material or the full generated answer.

- [ ] **Step 9: Inspect the UI in a real browser**

Run the Flask app locally and verify:

1. The third tab fits beside the first two at desktop width and remains usable at the existing mobile breakpoint.
2. Opening the Codex tab automatically fills the complete detected path in `codex-path`.
3. Runtime source, version, and login state are visible.
4. Clicking “自动检测” ignores the current value and fills the newest desktop path.
5. Invalid manual paths show an actionable message without erasing the entered value.
6. Manual and API modes still switch and render correctly.

- [ ] **Step 10: Commit only Task 5 files**

```powershell
git add -- tests/test_test_page.py templates/index.html static/app.js static/styles.css README.md
git diff --cached --check
git commit -m "feat: add Codex automatic testing UI"
```

---

## Final Verification

After all task reviews are clean, run:

```powershell
python -m unittest discover -s tests -v
node --test tests/js/automatic-test-core.test.mjs
node --check static/automatic-test-core.mjs
node --check static/app.js
git diff --check main...HEAD
git status --short --branch
```

Confirm the branch diff contains no changes to fingerprint algorithms, reference data, generated banks, or the user’s existing DeepSeek files. Run a final whole-branch code review against `git merge-base main HEAD`. Do not push, merge, or publish without an explicit user request.
