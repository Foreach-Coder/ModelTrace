# Codex 用户配置模式实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为现有 Codex 自动测试增加默认关闭的“读取 Codex 用户配置（兼容 Codex++）”开关，并向页面展示 Codex CLI 返回的真实脱敏错误。

**Architecture:** 前端将严格布尔值 `use_user_config` 发送到现有 Codex probe；路由只负责默认值、类型校验和转发；`codex_runner.py` 集中决定是否加入 `--ignore-user-config`。两种模式统一启用 `--json` 事件输出，失败时优先提取结构化错误，最终回答仍从 `--output-last-message` 临时文件读取。

**Tech Stack:** Python 3、Flask、标准库 `unittest`/`unittest.mock`、原生 JavaScript ES modules、Node.js `node:test`、HTML/CSS。

**Spec:** `docs/superpowers/specs/2026-10-15-codex-user-config-mode-design.md`

## Global Constraints

- 仅支持 Windows；不扩展 Linux 或 macOS 行为。
- 禁止使用 Git worktree；所有工作在当前 `dev-foreach` 工作区完成。
- 未经用户明确授权禁止提交代码；本计划不执行 `git commit`。
- `use_user_config` 省略时必须等价于 `false`，旧调用保持隔离模式。
- 开关关闭时必须传入且只传入一个 `--ignore-user-config`；开启时不得传入该参数。
- 两种模式都显式传入页面选择的模型和推理强度，并保留 `--ephemeral`、`--sandbox read-only`、超时、子进程树回收和临时文件清理。
- 不读取或修改 Codex++ 内部配置，不探测代理，不把底层错误改写为 Codex++ 状态结论。
- 错误可以提取和解包，但只能做结构清理、长度限制和凭据脱敏，不改变实际错误语义。
- 不修改指纹算法、挑战内容、自动测试判定逻辑或任何指纹数据文件。
- 所有生产代码遵循 RED → GREEN → REFACTOR；新增行为的测试必须先失败且失败原因是行为尚未实现。

---

### Task 1: Codex runner 配置模式与真实错误提取

**Files:**
- Modify: `tests/test_codex_runner.py`
- Modify: `codex_runner.py`

**Interfaces:**
- Consumes: `request_codex_completion(codex_path, model, reasoning_effort, prompt, timeout=120)`。
- Produces: `request_codex_completion(codex_path, model, reasoning_effort, prompt, timeout=120, use_user_config=False) -> str`。
- Produces: 默认模式包含 `--json --ignore-user-config`；用户配置模式只省略 `--ignore-user-config`。
- Produces: 非零退出优先使用 JSONL 中最后一个 `error`/`turn.failed` 消息，找不到时回退到脱敏后的 stderr 尾部。

- [ ] **Step 1: 扩展测试替身，使 stdout 可控**

在 `CodexExecutionTests.setUp` 增加 `self.stdout = ""`。给 `FakeCodexProcess` 增加 `stdout` 构造参数并让 `communicate` 返回 `(self.stdout, self.stderr)`；保留其真实临时文件写入、缺失文件、kill 和 reap 行为。

- [ ] **Step 2: 先写命令模式失败测试**

测试辅助方法增加 `use_user_config=False`，并用关键字传给生产函数。更新固定参数期望，使默认命令以如下字面量开头：

```python
[
    str(self.codex.resolve()), "exec", "--json", "--ignore-user-config",
    "--model", "gpt-6-astra", "-c", 'model_reasoning_effort="low"',
]
```

新增 `test_exec_user_config_mode_omits_only_ignore_user_config`：分别调用 `False` 和 `True`，断言前者恰有一个 `--ignore-user-config`，后者没有，并断言删除该单个元素后两个完整参数列表相等。

- [ ] **Step 3: 运行命令模式测试并确认 RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_codex_runner.CodexExecutionTests.test_exec_uses_fixed_safe_arguments_and_sends_prompt_on_stdin tests.test_codex_runner.CodexExecutionTests.test_exec_user_config_mode_omits_only_ignore_user_config -v
```

Expected: FAIL，因为生产签名尚不接受 `use_user_config`，命令也尚未包含 `--json`。

- [ ] **Step 4: 最小实现命令模式并确认 GREEN**

签名追加 `use_user_config: bool = False`，保留 `timeout` 的位置兼容性。参数使用列表构造：

```python
args = [runtime.path, "exec", "--json"]
if not use_user_config:
    args.append("--ignore-user-config")
args.extend([
    "--model", model,
    "-c", f'model_reasoning_effort="{reasoning_effort}"',
    "--ephemeral", "--sandbox", "read-only", "--skip-git-repo-check",
    "--output-last-message", str(output_path), "-",
])
```

重新运行 Step 3，Expected: PASS。

- [ ] **Step 5: 先写结构化错误与脱敏失败测试**

新增 `test_exec_prefers_actual_structured_error_over_startup_warnings`。令 stdout 包含真实 JSONL：`thread.started`、`error`、`turn.failed`；两个错误事件的消息为 JSON 字符串包装的 `tools.12: tool type "tool_search" is not supported`。stderr 放入 `plugin catalog warning`。断言异常包含实际工具错误且不包含 warning。

新增结构化消息凭据测试：消息包含 `api_key=secret-key`、`Bearer secret-bearer`、`token="secret-token"` 和 `sk-secretvalue`，断言错误语义保留、所有 secret 消失。

调整现有长 stderr 测试：使用超过限制的开头警告和结尾 `actual final error`，断言结尾错误仍在、开头被截断且异常总长度受限。该测试保护“不能只截取日志开头”。

- [ ] **Step 6: 运行错误测试并确认 RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_codex_runner.CodexExecutionTests.test_exec_prefers_actual_structured_error_over_startup_warnings tests.test_codex_runner.CodexExecutionTests.test_exec_redacts_credentials_and_control_sequences_in_diagnostics tests.test_codex_runner.CodexExecutionTests.test_exec_maps_nonzero_exit_to_sanitized_execution_error -v
```

Expected: 至少结构化错误测试 FAIL，因为生产代码仍忽略 stdout 并截取 stderr 开头。

- [ ] **Step 7: 最小实现结构化错误提取**

引入标准库 `json`。新增 `_unwrap_error_message(value) -> str`：接受字符串或 `{"message": ...}`，最多解包两层 JSON 字符串，并提取 `{"error":{"message":...}}` 或顶层 `message`。新增 `_structured_error(stdout) -> str`：逐行 `json.loads`，只处理 `error.message` 与 `turn.failed.error`，跳过畸形行，返回最后一个非空消息。

让 `_sanitized_diagnostic` 完成全部脱敏和空白规范化后保留最多 1000 个字符；超长文本取尾部。`communicate` 保存 `stdout, stderr`，非零退出使用：

```python
raw_diagnostic = _structured_error(stdout) or stderr
diagnostic = _sanitized_diagnostic(raw_diagnostic)
```

- [ ] **Step 8: 运行 runner 全文件并确认 GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_codex_runner -v
```

Expected: 全部 PASS；不产生真实模型请求。

- [ ] **Step 9: 自审并报告**

确认测试能捕获分支反转、stdout 未解析、凭据未脱敏以及临时文件未清理。不要提交，将 RED/GREEN 命令和结果写入子任务报告。

---

### Task 2: Flask probe 严格布尔契约

**Files:**
- Modify: `tests/test_codex_routes.py`
- Modify: `codex_routes.py`

**Interfaces:**
- Consumes: Task 1 的 `request_codex_completion(..., timeout=120, use_user_config=False)`。
- Produces: `POST /api/test/codex/probe` 接受可选 JSON 布尔字段 `use_user_config`。
- Produces: 路由用关键字参数 `use_user_config=<bool>` 调用 runner。

- [ ] **Step 1: 先写默认值和显式布尔失败测试**

更新现有成功断言：省略字段时必须调用：

```python
completion.assert_called_once_with(
    "C:/Codex/codex.exe", "gpt-5.4", "high", "Return 100 integers.",
    use_user_config=False,
)
```

新增 `test_probe_forwards_explicit_user_config_mode`，遍历 `(False, True)`，提交对应 JSON 值并断言状态 200、runner 收到相同布尔关键字参数。

- [ ] **Step 2: 先写非法类型失败测试**

把 `use_user_config` 加入无效输入表，值为 `[None, "true", "false", 0, 1, [], {}]`。每个请求必须返回 400 且 runner 未调用。

- [ ] **Step 3: 运行路由测试并确认 RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_codex_routes.CodexRouteTests -v
```

Expected: FAIL，因为路由尚未读取、校验或转发新字段。

- [ ] **Step 4: 最小实现路由契约**

读取并严格校验：

```python
use_user_config = payload.get("use_user_config", False)
if type(use_user_config) is not bool:
    raise ValueError("use_user_config 必须是布尔值")
```

调用 runner：

```python
text = request_codex_completion(
    codex_path, model, reasoning_effort, prompt,
    use_user_config=use_user_config,
)
```

- [ ] **Step 5: 运行路由和 runner 回归并确认 GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_codex_routes tests.test_codex_runner -v
```

Expected: 全部 PASS。

- [ ] **Step 6: 自审并报告**

确认 Python 整数不会被当作布尔值，旧请求默认 `false`，路由不读取 Codex++ 文件也不产生代理文案。不要提交，将 RED/GREEN 结果写入报告。

---

### Task 3: 前端开关、偏好持久化与请求载荷

**Files:**
- Modify: `tests/js/automatic-test-core.test.mjs`
- Modify: `tests/test_test_page.py`
- Modify: `static/automatic-test-core.mjs`
- Modify: `static/app.js`
- Modify: `templates/index.html`
- Modify: `static/styles.css`

**Interfaces:**
- Consumes: Task 2 的 `use_user_config: bool` 字段。
- Produces: 偏好字段 `useUserConfig: boolean`，缺失或类型错误时为 `false`。
- Produces: DOM 元素 `#codex-use-user-config`，提交时映射为 `use_user_config`。

- [ ] **Step 1: 先写偏好失败测试**

更新 `readCodexPreferences` 的所有期望对象，增加 `useUserConfig: false`。错误类型 fixture 传入 `useUserConfig: "true"`，仍期望 `false`。持久化测试传入 `useUserConfig: true`，保存结果必须精确保留 `true`，仍丢弃 `authenticated`、`pathSource` 等非偏好字段。

- [ ] **Step 2: 运行 JS 偏好测试并确认 RED**

Run:

```powershell
node --test tests/js/automatic-test-core.test.mjs
```

Expected: FAIL，因为规范化结果尚无 `useUserConfig`。

- [ ] **Step 3: 最小实现偏好字段并确认 GREEN**

在 `normalizedPreferences` 返回值增加：

```javascript
useUserConfig: typeof preferences?.useUserConfig === "boolean"
  ? preferences.useUserConfig
  : false,
```

重新运行 Step 2，Expected: PASS。

- [ ] **Step 4: 先写页面结构和真实 UI 行为失败测试**

首页结构测试验证 `id="codex-use-user-config"`、`type="checkbox"` 和文案“读取 Codex 用户配置（兼容 Codex++）”。Node DOM 替身增加 `checked: false`，并把新元素加入 Codex controls。所有现有保存偏好字面量增加 `useUserConfig: false`。

新增行为场景，执行真实 `static/app.js` 并验证：本地偏好 `useUserConfig: true` 恢复 checkbox；Codex 表单发送到 `/api/test/codex/probe` 的挑战载荷包含 `use_user_config: true`；成功后保存偏好仍为 `true`。只替换 DOM、HTTP 和 localStorage 边界，不复制生产载荷逻辑到测试。

- [ ] **Step 5: 运行页面测试并确认 RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_test_page -v
```

Expected: FAIL，因为 checkbox 和生产字段映射尚不存在。

- [ ] **Step 6: 最小实现 HTML 与 CSS**

在 Codex `.form-grid` 内加入：

```html
<label class="codex-config-toggle">
  <input id="codex-use-user-config" type="checkbox">
  <span>读取 Codex 用户配置（兼容 Codex++）</span>
</label>
```

增加样式，避免全局文本输入规则拉伸 checkbox：

```css
.codex-config-toggle { grid-column: 1 / -1; flex-direction: row; align-items: center; gap: 8px; }
.codex-config-toggle input { width: 16px; height: 16px; padding: 0; flex: 0 0 auto; }
```

- [ ] **Step 7: 最小实现恢复、保存和提交**

`saveCodexPreferences` 保存 `useUserConfig: byId("codex-use-user-config").checked`；`initializeCodex` 恢复 `checked = preferences.useUserConfig`；Codex probe configuration 发送 `use_user_config: byId("codex-use-user-config").checked`。不增加服务器端持久化。

- [ ] **Step 8: 运行前端测试并确认 GREEN**

Run:

```powershell
node --test tests/js/automatic-test-core.test.mjs
.\.venv\Scripts\python.exe -m unittest tests.test_test_page -v
```

Expected: 全部 PASS。

- [ ] **Step 9: 自审并报告**

确认开关是原生二元控件、默认关闭、移动端不溢出、不显示代理状态，也不把 Base URL 或认证信息写入 localStorage。不要提交，将 RED/GREEN 结果写入报告。

---

### Task 4: 集成回归与 Windows 真实穿刺

**Files:**
- Verify only: Tasks 1-3 的全部修改

**Interfaces:**
- Consumes: 完整未提交工作区。
- Produces: 自动化回归证据和一次真实 `deepseek-flash` 用户配置模式 probe 结果。

- [ ] **Step 1: 运行 Python 全量测试**

Run: `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`

Expected: 0 failures，0 errors。

- [ ] **Step 2: 运行 JavaScript 全量测试**

Run: `node --test tests/js/automatic-test-core.test.mjs`

Expected: 全部 PASS。

- [ ] **Step 3: 检查修改范围**

依次运行 `git status --short`、`git diff --check`、`git diff --stat`。Expected: 只包含 spec、plan 和 Tasks 1-3 列出的文件；无指纹算法或 `data/` 变更；diff check 无输出。

- [ ] **Step 4: 运行一次真实 deepseek-flash probe**

先只记录 `127.0.0.1:57321` 是否监听，不据此转换错误。调用：

```python
request_codex_completion(
    codex_path="",
    model="deepseek-flash",
    reasoning_effort="xhigh",
    prompt="This is a connectivity probe. Do not use tools. Reply with exactly: MODELTRACE_DEEPSEEK_OK",
    timeout=90,
    use_user_config=True,
)
```

Expected: 精确返回 `MODELTRACE_DEEPSEEK_OK`。若外部服务状态变化导致失败，如实记录脱敏后的实际错误，不修改产品代码迎合临时环境。

- [ ] **Step 5: 最终代码审查**

审查全部未提交 diff，重点检查默认关闭、严格布尔、两模式只差一个参数、错误脱敏、失败清理和前端真实模块测试。任何真实缺陷先增加失败测试，再修复并复跑相关套件。

- [ ] **Step 6: 保持未提交并报告**

不提交、不推送。报告修改文件、自动化测试计数、真实 probe 结果、残余兼容性限制以及工作区仍未提交的状态。
