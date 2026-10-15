# Codex 用户配置模式设计

## 背景

ModelTrace 的“Codex 自动测试”当前固定向 `codex exec` 传入
`--ignore-user-config`。这种隔离模式不会读取 `$CODEX_HOME/config.toml`，可以避免用户配置改变
测试请求，但也无法使用由 Codex++ 或其他工具写入 Codex 用户配置的模型提供方、Base URL 和认证方式。

在 Windows 本机进行的受控验证表明：

- 保留 `--ignore-user-config` 时，请求不会使用 Codex++ 写入的本地代理配置。
- 移除该参数后，Codex CLI 会读取用户配置并将请求发送到配置的提供方。
- `deepseek-flash` 已通过该方式成功返回预期测试文本。
- `k3` 请求能够到达配置的上游，但上游拒绝了不支持的 `tool_search` 工具类型。

因此，本功能不是增加一种新的测试或指纹算法，而是为现有 Codex 请求传输增加一种用户可选的配置加载模式。

## 目标

- 在“Codex 自动测试”表单中增加“读取 Codex 用户配置（兼容 Codex++）”开关。
- 默认保持当前隔离行为，确保已有用户和测试结果不受影响。
- 开启后允许 Codex CLI 读取用户的 `config.toml`，从而使用其中配置的提供方、代理和认证方式。
- 继续复用现有挑战生成、输出校验、重试、进度展示和指纹归因流程。
- 将 Codex CLI 返回的实际错误展示给用户，不根据错误现象推断 Codex++ 或其他外部组件的状态。
- 保持凭据脱敏，不向浏览器返回 API Key、Bearer Token 或其他认证信息。

## 非目标

- 不检测用户是否安装或正在使用 Codex++。
- 不读取、解析或修改 Codex++ 的内部配置文件。
- 不探测或展示用户配置中的代理地址、API Key 或认证内容。
- 不根据端口连接失败推断“Codex++ 代理未运行”。
- 不自动启动、停止或重启任何代理进程。
- 不为外部模型自动删除、转换或降级 Codex 工具定义。
- 不承诺所有第三方模型或代理完整兼容 Codex CLI 请求协议。
- 不修改指纹算法、挑战内容、指纹库或归因流程。

## 用户界面

在现有 Codex 路径、模型和推理强度配置附近增加一个布尔开关：

```text
读取 Codex 用户配置（兼容 Codex++）  [关闭/开启]
```

开关默认关闭。浏览器通过现有 Codex 测试偏好存储保存最后一次选择，刷新页面后恢复。

两种模式的界面语义如下：

| 模式 | 行为 |
| --- | --- |
| 关闭 | 忽略 Codex 用户配置，保持当前隔离测试行为 |
| 开启 | 读取 Codex 用户配置，可使用 Codex++ 或其他方式配置的模型提供方 |

运行时状态仍只显示 `codex.exe` 路径来源、版本和登录状态。界面不显示“已检测到 Codex++”之类的结论，也不增加代理状态判断。

模型和推理强度输入在两种模式下都保留。它们仍作为本次调用的显式参数，优先于用户配置中的默认模型和默认推理强度；用户配置主要提供模型提供方、Base URL、认证以及其他 Codex 配置。

## HTTP 接口

`POST /api/test/codex/probe` 增加可选布尔字段 `use_user_config`：

```json
{
  "codex_path": "C:\\optional\\path\\codex.exe",
  "model": "deepseek-flash",
  "reasoning_effort": "xhigh",
  "use_user_config": true,
  "prompt": "...",
  "expected_count": 311
}
```

字段规则：

- 省略时按 `false` 处理，以保持向后兼容。
- 只接受 JSON 布尔值，不接受字符串 `"true"`、数字或空值。
- 非法值返回 HTTP 400，且不启动 Codex 子进程。

`POST /api/codex/status` 不增加 Codex++ 或代理参数。可执行文件发现和登录状态检查与当前实现保持一致。

## Codex 命令构造

`codex_routes.py` 将 `use_user_config` 传递给 `request_codex_completion`。`codex_runner.py` 继续集中负责命令构造，其他模块不直接判断模式。

关闭开关时保持现有命令：

```text
codex.exe exec
  --json
  --ignore-user-config
  --model <model>
  -c model_reasoning_effort="<effort>"
  --ephemeral
  --sandbox read-only
  --skip-git-repo-check
  --output-last-message <temporary-file>
  -
```

开启开关时仅移除 `--ignore-user-config`：

```text
codex.exe exec
  --json
  --model <model>
  -c model_reasoning_effort="<effort>"
  --ephemeral
  --sandbox read-only
  --skip-git-repo-check
  --output-last-message <temporary-file>
  -
```

`--json` 是两种模式共有的诊断参数，只将 CLI 事件流改为结构化输出；最终模型回答仍从
`--output-last-message` 指定的临时文件读取。除配置加载行为外，两种模式使用相同的可执行文件校验、登录检查、标准输入、临时会话、只读沙盒、超时、进程树回收和临时文件清理逻辑。

## 错误处理

ModelTrace 不把底层错误转换成对 Codex++ 状态的猜测。例如，连接拒绝只显示连接拒绝，不改写为“Codex++ 代理未运行”。HTTP 状态码、模型不可用、工具类型不受支持等错误同样保留 Codex CLI 返回的实际含义。

为了避免启动阶段的普通警告覆盖真正的失败原因，Codex 执行应使用 CLI 的结构化事件输出提取错误：

1. 从 `error` 或 `turn.failed` 事件获取实际错误消息。
2. 没有结构化错误事件时，回退到标准错误输出。
3. 移除 ANSI 控制符，并对 API Key、Bearer Token、`sk-` 前缀密钥和常见 token 字段脱敏。
4. 限制返回文本长度，防止将完整内部日志发送到页面，但不能只截取日志开头而丢失最终错误。
5. 不对错误做 Codex++ 专属分类或文案替换。

页面沿用每次挑战失败后继续下一道挑战的行为。错误摘要展示后端返回的脱敏消息，例如：

```text
tools.12: tool type "tool_search" is not supported
```

## 兼容性边界

读取用户配置只决定 Codex CLI 从哪里获得提供方配置，不改变 Codex CLI 发送给模型的请求能力集合。外部提供方必须自行兼容请求中出现的字段和工具类型。

首版不针对 `k3` 的 `tool_search` 错误增加自动修复或隐藏开关，原因如下：

- 该错误属于当前上游的协议兼容性结果，不是 ModelTrace 的连接错误。
- 自动删除工具可能改变 Codex 行为，导致测试条件与用户真实使用环境不一致。
- 不同模型和代理支持的能力不同，不应根据模型名称维护隐式规则。

因此，兼容模型可以正常完成自动测试；不兼容模型会在当前挑战中显示其实际错误，并继续后续尝试。

## 前端状态与数据流

开关值加入现有 `modeltrace.codex-test.preferences`：

```json
{
  "manualPath": "",
  "model": "deepseek-flash",
  "reasoningEffort": "xhigh",
  "useUserConfig": true
}
```

旧版偏好没有 `useUserConfig` 时规范化为 `false`。类型不是布尔值时同样回退为 `false`。

提交一次挑战时的数据流为：

```text
Codex 表单开关
  -> use_user_config
  -> /api/test/codex/probe
  -> request_codex_completion(..., use_user_config)
  -> 有条件地添加 --ignore-user-config
  -> Codex CLI
  -> 现有 evaluate_probe
  -> 现有自动测试调度与指纹归因
```

开关只影响 Codex probe，不影响 API 自动测试或手动测试。

## 安全性

- `use_user_config` 必须是严格布尔值，不能映射为任意命令行参数。
- 后端仍使用参数数组和 `shell=False` 启动 Codex。
- 页面不能提交自定义 Base URL、认证字段或附加 CLI 参数到该接口。
- 开启后，Codex CLI 会按其自身规则加载用户配置中的提供方、MCP、插件及其他设置；ModelTrace 不复制或持久化这些内容。
- 所有模式继续使用 `--ephemeral` 和 `--sandbox read-only`。
- 错误返回必须先脱敏，再进入 Flask 响应和浏览器界面。
- 测试和日志不得记录用户配置文件原文或认证内容。

## 修改范围

预计修改：

- `templates/index.html`：增加配置模式开关。
- `static/app.js`：恢复、保存和提交开关值。
- `static/automatic-test-core.mjs`：规范化并持久化 `useUserConfig`。
- `codex_routes.py`：校验并转发 `use_user_config`。
- `codex_runner.py`：根据模式构造参数，并改进实际错误提取与脱敏。
- `tests/test_test_page.py`：覆盖开关交互和请求载荷。
- `tests/js/automatic-test-core.test.mjs`：覆盖偏好默认值、类型校验和持久化。
- `tests/test_codex_routes.py`：覆盖接口默认值、布尔校验和参数转发。
- `tests/test_codex_runner.py`：覆盖两种命令、结构化错误提取和凭据脱敏。

不修改：

- `fingerprint.py`
- `bank_builder.py`
- `challenge_suite.py`
- `automatic_testing.py`
- `data/` 下的指纹原始数据和生成库
- Codex 插件中的统一指纹库

## 测试策略

采用 TDD，先写失败测试，再实现最小改动。

单元和接口测试覆盖：

- 开关默认关闭时命令包含且只包含一个 `--ignore-user-config`。
- 开关开启时命令不包含 `--ignore-user-config`，其他固定参数保持一致。
- 两种模式都包含 `--json`，并继续从 `--output-last-message` 文件读取最终回答。
- 接口省略 `use_user_config` 时向 runner 传递 `false`。
- 接口接受 `true` 和 `false`，拒绝字符串、数字、数组、对象及 `null`。
- 旧版浏览器偏好迁移后默认关闭，新版偏好能正确保存和恢复。
- 前端提交载荷使用蛇形字段 `use_user_config`。
- 结构化 CLI 错误优先于启动警告展示。
- 错误中的认证字段被脱敏，普通错误语义不被改写。
- 超时、空输出、进程回收和临时文件删除行为无回归。
- API 自动测试、通用输出评估和指纹归因测试保持通过。

Windows 手工验证覆盖：

1. 关闭开关，以现有隔离模式完成或发起一次 Codex probe。
2. 开启开关，确认 `deepseek-flash` 通过 Codex++ 配置返回有效回答。
3. 开启开关并调用当前不兼容的 `k3`，确认页面显示实际 `tool_search` 错误，而不是代理状态推断。
4. 停止或更改外部代理后，确认页面显示 Codex CLI 返回的实际连接错误。
5. 确认整个过程不显示或记录 API Key 与 Token。

## 验收标准

- Codex 自动测试页面提供“读取 Codex 用户配置（兼容 Codex++）”开关，默认关闭。
- 关闭时保持现有 `--ignore-user-config` 行为，已有自动测试不受影响。
- 开启时不传 `--ignore-user-config`，Codex CLI 能读取用户配置。
- 模型和推理强度继续由表单显式控制。
- `deepseek-flash` 能通过当前 Codex++ 配置完成真实 probe。
- 不兼容请求显示 Codex CLI 的实际脱敏错误，不推断 Codex++ 是否运行。
- 开关设置可以安全保存和恢复，旧偏好向后兼容。
- 自动化测试全部通过，且 Git diff 不包含任何指纹算法或指纹库修改。
