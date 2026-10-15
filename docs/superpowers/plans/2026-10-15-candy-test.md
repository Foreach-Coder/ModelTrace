# 糖果测试 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 ModelTrace 中新增独立的糖果测试页面，通过 API 或 Windows Codex CLI 顺序执行固定轮次，并准确展示判分、耗时和可用 token 用量。

**Architecture:** 新建纯函数评测模块作为题目和判分的唯一来源；API 与 Codex 请求层各提供结构化的单轮完成结果，同时保留旧的文本返回接口。Flask 路由只做输入校验和错误映射；浏览器模块只编排当前批次，页面不持久化结果。

**Tech Stack:** Python 3、Flask、`unittest`、原生 JavaScript ES modules、Node.js `node:test`、HTML/CSS。

**Spec:** `docs/superpowers/specs/2026-10-15-candy-test-design.md`

## Global Constraints

- 禁止使用 Git worktree；未经用户明确授权，禁止提交代码。本计划执行期间不创建提交。
- 仅支持 Windows Codex；保留 Codex++ 用户配置开关及现有路径、模型目录能力。
- API 和 Codex 每轮默认超时均为 600 秒，界面允许 30～1800 秒整数。
- 默认 5 轮，界面允许 1～50 轮；失败占用该轮并继续，不由应用自动重试、补测或切换协议。
- 题目标识为 `candy-v1`；标准答案 21 只存在于后端判分逻辑，不进入发送给模型的提示词或题目接口。
- 最终答案必须是回答末尾唯一的 `<final-answer>整数</final-answer>`；其他格式为待判定。
- 只保留当前批次；API Key、回答和结果不得持久化。
- 界面只保留与操作和结果理解直接相关的信息，不用小字展示开发要求、实现细节、内部约束或代码注释。
- 指纹提取、归因算法、指纹库和 `unified_bank.json` 不得改动。

---

### Task 1: 糖果题定义与纯函数判分

**Files:**
- Create: `candy_testing.py`
- Create: `tests/test_candy_testing.py`

**Interfaces:**
- Produces: `question_payload() -> dict[str, str]`
- Produces: `grade_candy_answer(text: str) -> dict[str, object]`
- Produces: `build_candy_result(text, usage, elapsed_seconds) -> dict[str, object]`
- Constants: `CANDY_QUESTION_ID = "candy-v1"`, `DEFAULT_TIMEOUT_SECONDS = 600`

- [x] **Step 1: Write failing question and grading tests**

Add table-driven tests with literal expected results for: valid 21, valid non-21, a `21` only in reasoning, missing tag, duplicate tag, attributes, unclosed/nested tags, decimal/unit content, content after closing tag, surrounding whitespace, and a normal “无法回答” response. Assert `question_payload()` contains the full prompt and format tag but not the standard answer as answer metadata.

- [x] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_candy_testing -v`

Expected: import failure because `candy_testing.py` does not exist.

- [x] **Step 3: Implement the minimal evaluator**

Use a single strict full-answer regex after separately counting literal opening and closing tags. Return statuses `correct`, `incorrect`, or `ungraded`, a nullable integer `final_answer`, and a stable Chinese `grading_reason`. `question_payload()` returns only `question_id`, `title`, and `prompt`.

- [x] **Step 4: Add failing structured-result tests, then implement**

Test that `build_candy_result()` preserves nullable usage values, computes `tps = output_tokens / elapsed_seconds` only when both are valid, and leaves it null otherwise. Run RED before adding the function body.

- [x] **Step 5: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_candy_testing -v`

Expected: all task tests pass with no warnings.

### Task 2: API 单次调用与结构化用量

**Files:**
- Modify: `enrollment.py`
- Modify: `tests/test_api_probe.py`

**Interfaces:**
- Produces: `request_completion_result(base_url, api_key, api_model, prompt, temperature, api_format, timeout=600, max_attempts=1) -> dict[str, object]`
- Result shape: `{text, usage: {input_tokens, output_tokens, reasoning_tokens}}`
- Preserves: `request_completion(...) -> str` and its existing retries/protocol auto-detection for all old callers.

- [x] **Step 1: Write failing protocol tests**

Cover OpenAI and Anthropic literal response fixtures, including nullable usage, zero usage, OpenAI reasoning tokens, Anthropic cache input tokens, explicit timeout propagation, `max_attempts=1`, no protocol fallback, normal refusal/truncation handling, and unchanged legacy `request_completion()` behavior.

- [x] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_api_probe -v`

Expected: failures for the missing structured function and unsupported timeout/attempt configuration.

- [x] **Step 3: Extract structured response parsing and configurable attempts**

Refactor the existing request code so URL construction, headers, response parsing, and error compaction remain shared. Keep legacy defaults unchanged. For the new structured entry point require an explicit `openai` or `anthropic` format and one application attempt.

- [x] **Step 4: Run GREEN and legacy API tests**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_api_probe tests.test_automatic_testing -v`

Expected: all selected tests pass with no warnings.

### Task 3: Codex 结构化结果与 token 事件解析

**Files:**
- Modify: `codex_runner.py`
- Modify: `tests/test_codex_runner.py`

**Interfaces:**
- Produces: `request_codex_completion_result(codex_path, model, reasoning_effort, prompt, timeout=600, use_user_config=False) -> dict[str, object]`
- Result shape: `{text, usage: {input_tokens, output_tokens, reasoning_tokens}}`
- Preserves: `request_codex_completion(...) -> str` and its existing default timeout/behavior for fingerprint testing.

- [x] **Step 1: Write failing JSONL usage tests**

Use complete Codex JSONL fixtures for a successful `turn.completed`, missing reasoning usage, malformed unrelated lines, multiple completion events, empty final answer, timeout, and user-config argument construction. Assert credentials in errors remain sanitized.

- [x] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_codex_runner -v`

Expected: failures for the absent structured entry point and usage parser.

- [x] **Step 3: Extract one shared execution path**

Parse the last valid `turn.completed.usage`, read final text from the existing output file, return nullable token fields, and expose the 600-second default only through the new entry point. Keep process-tree termination, temporary-file cleanup, path/login validation, and legacy wrapper semantics.

- [x] **Step 4: Run GREEN**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_codex_runner -v`

Expected: all task tests pass with no warnings.

### Task 4: 糖果测试 HTTP 接口

**Files:**
- Create: `candy_routes.py`
- Modify: `app.py`
- Create: `tests/test_candy_routes.py`

**Interfaces:**
- Consumes: Task 1 evaluator and Tasks 2–3 structured completion functions.
- Produces: `GET /api/candy/question`
- Produces: `POST /api/candy/api/probe`
- Produces: `POST /api/candy/codex/probe`

- [x] **Step 1: Write failing route tests**

Test the exact public payloads for question retrieval, correct/incorrect/ungraded results, structured failures with elapsed time, question-version 409, validation 400 before any model call, API explicit format, default/custom timeout bounds, and Codex user-config forwarding. Confirm response JSON never contains the API Key.

- [x] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_candy_routes -v`

Expected: 404/import failures because the blueprint is absent.

- [x] **Step 3: Implement route validation and timed probes**

Register a dedicated blueprint. Validate booleans by exact type, integer bounds without accepting booleans, model/path fields consistently with existing routes, and `question_id` before invoking transport. Measure each single probe with `time.perf_counter()` and build the shared result. Convert model-call exceptions into `status="error"` result JSON with real sanitized error text and HTTP 200; reserve HTTP 400/409 for invalid requests/version mismatch.

- [x] **Step 4: Run GREEN and existing route tests**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_candy_routes tests.test_codex_routes tests.test_api_probe -v`

Expected: all selected tests pass with no warnings.

### Task 5: 浏览器批次编排核心

**Files:**
- Create: `static/candy-test-core.mjs`
- Create: `tests/js/candy-test-core.test.mjs`

**Interfaces:**
- Produces: `runCandyBatch({rounds, probe, onUpdate, shouldStop})`
- Produces: `summarizeCandyResults(results, plannedRounds)`
- Produces: `validateCandySettings({rounds, timeoutSeconds})`
- Result statuses: `correct`, `incorrect`, `ungraded`, `error`, `not_run`.

- [x] **Step 1: Write failing Node behavior tests**

Test strict 1–50 rounds and 30–1800 seconds validation, sequential ordering, one probe call per started round, continuation after error results and thrown request errors, stop-after-current behavior, untouched rounds becoming `not_run`, immediate immutable progress snapshots, and correct-rate denominator excluding ungraded/error/not-run.

- [x] **Step 2: Run RED**

Run: `node --test tests/js/candy-test-core.test.mjs`

Expected: module-not-found failure.

- [x] **Step 3: Implement the minimal orchestration module**

Keep DOM access out of the module. Convert a thrown request failure into one `error` result, then continue unless `shouldStop()` is true. Return final `results` and `summary`; do not persist data or retry.

- [x] **Step 4: Run GREEN and existing JS tests**

Run: `node --test tests/js/candy-test-core.test.mjs tests/js/automatic-test-core.test.mjs`

Expected: all selected tests pass with no warnings.

### Task 6: 独立页面、交互与结果呈现

**Files:**
- Modify: `templates/index.html`
- Modify: `static/app.js`
- Modify: `static/styles.css`
- Modify: `tests/test_test_page.py`

**Interfaces:**
- Consumes: Task 4 HTTP endpoints and Task 5 batch functions.
- Reuses: existing Codex runtime detection, model catalog, selection menu, and preference storage.

- [x] **Step 1: Write failing page behavior tests**

Add server-rendered DOM assertions for the independent sidebar workspace, API/Codex tabs, question disclosure, both 600-second timeout inputs, 5-round defaults, start/stop controls, summary region, result rows, and answer disclosure. Add executable JS/static checks only for behavior that can be observed without duplicating source text assertions.

- [x] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_test_page -v`

Expected: failures for missing candy workspace controls.

- [x] **Step 3: Build the page and connect batch execution**

Add the third workspace between model testing and library management. Fetch the question from the backend for the visible disclosure and freeze that prompt snapshot when a batch starts. Disable batch configuration during execution; preserve the current batch while navigating or switching transport tabs; clear it only after a valid new run starts or page refreshes. Render all model text with `textContent`/escaped HTML, never raw HTML. Reuse Codex helpers by parameterizing them rather than duplicating path/model behavior.

- [x] **Step 4: Apply concise UI styling**

Use existing form, tab, table, badge, progress, and disclosure visual language. Present field labels, status, actual errors, and result meanings only. Do not add explanatory small-print about internal retries, implementation architecture, hidden standard answers, JSON fields, or development constraints.

- [x] **Step 5: Run GREEN and full automated suites**

Run: `.\.venv\Scripts\python.exe -m unittest discover -s tests -q`

Run: `node --test tests/js/*.test.mjs`

Expected: all Python and JavaScript tests pass with no warnings or failures.

- [x] **Step 6: Verify the real page visually**

Start the application through the project launcher, open `http://127.0.0.1:7862/`, and verify desktop width plus one narrow viewport. Confirm the independent page, prompt disclosure, API/Codex tab switching, model menu, 600-second defaults, readable results, expanded answers, stop state, and absence of developer-oriented small print. Use mocked/local endpoint behavior for UI state verification; do not incur real external model calls during automated verification.

## Plan Self-Review

- Spec coverage: tasks cover the question source and version, strict grading, API/Codex structured usage, route validation, fixed-round orchestration, stop behavior, transient state, full UI, errors, timeouts, and legacy compatibility.
- File ownership: Tasks 2 and 4 share the structured API interface; Tasks 3 and 4 share the structured Codex interface; Tasks 4 and 6 share endpoint payloads; Tasks 5 and 6 share batch result/status names. Each producer task precedes its consumer.
- TDD order: every production-code task begins with a behavior test and an observed RED command before implementation.
- Repository rules: no worktree and no commits; `.gitignore` remains an unrelated user change unless separately requested.
