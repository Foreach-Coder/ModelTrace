# Codex 自动测试设计

## 背景

ModelTrace 已经支持手动测试和基于 Base URL 的 API 自动测试。API 自动测试在浏览器中生成最多六道独立挑战，逐一请求模型，收集三份数字数量达标的输出，最后调用统一指纹库进行归因。

新功能在“模型测试”页增加第三个“Codex 自动测试”页签，通过 Windows 本机的 `codex.exe` 获取模型输出。它不建立新的指纹算法，只为现有自动测试流程增加一种模型请求传输。

## 目标

- 在现有两个测试页签后增加“Codex 自动测试”。
- 优先自动发现 Codex 桌面版内置的 `codex.exe`，并允许用户手动指定路径。
- 使用当前 Codex/ChatGPT 登录状态执行挑战，不再要求 Base URL 或 API Key。
- 复用现有挑战生成、输出校验、重试策略、指纹归因、进度和结果展示。
- 将 Codex 适配与指纹库数据、建库逻辑和归因算法隔离，降低未来合并新指纹库时的冲突风险。

## 非目标

- 第一版不支持 Linux 或 macOS。
- 不通过 Codex CLI 自动采集或重建指纹库。
- 不支持多个自动测试并发执行。
- 第一版不增加运行中取消按钮。
- 不修改指纹特征、概率校准方法或挑战内容。
- 不允许用户通过界面传入任意 Codex CLI 命令行参数。

## 架构与复用边界

自动测试被划分为“获取一次模型输出”和“评估输出并归因”两层：

```text
页面通用自动测试调度
  ├─ API probe   → request_completion(...)
  └─ Codex probe → request_codex_completion(...)

两种 probe 共同使用
  → generate_challenges
  → evaluate_probe（解析数字并判断是否达标）
  → 最多 6 次尝试，收集 3 份有效输出
  → analyze_global_outputs
  → 通用进度与归因结果组件
```

新建 `automatic_testing.py`，提供无传输依赖的 `evaluate_probe(text, expected_count)`。现有 API probe 和新 Codex probe 都调用它，确保有效数字门槛始终一致。`fingerprint.py`、`bank_builder.py` 和 `challenge_suite.py` 不因此功能修改。

新建 `codex_runner.py`，封装 Windows 运行时发现、状态检查、命令构造、子进程执行和错误转换。新建 `codex_routes.py` 作为 Flask Blueprint，使 `app.py` 只需注册路由并将现有 API probe 切换到通用输出评估函数。

## Windows Codex 运行时发现

界面中的 Codex 路径为可选文本配置。有效的手动路径始终优先；未填写时按以下顺序发现。自动发现成功后，后端返回解析后的完整路径，前端必须将该路径回填到 Codex 路径输入框，使用户可以直接看到本次测试实际使用的 `codex.exe`：

1. `MODELTRACE_CODEX_PATH` 环境变量。
2. `%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe` 中版本最新的可执行文件。
3. `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe`。
4. Windows `PATH` 中可解析到的 `codex.exe`。

每个候选文件必须是存在的普通文件，文件名必须为 `codex.exe`，并且能在短超时内成功执行 `--version`。桌面版多个版本候选按 `--version` 返回的语义版本选择最新者；无法解析版本时再使用文件修改时间排序。

状态检查额外执行 `codex login status`，以区分“未找到 CLI”、“CLI 可用但未登录”和“已就绪”。状态响应包含路径、来源、版本、登录状态和面向用户的错误文本，不包含任何登录凭据。

## Codex 执行方式

每道挑战启动一个独立的 `codex exec`，确保挑战之间没有会话历史污染。后端使用参数列表启动进程，不使用 shell；挑战 prompt 通过标准输入传递。固定命令语义为：

```text
codex.exe exec
  --ignore-user-config
  --model <model>
  -c model_reasoning_effort="<effort>"
  --ephemeral
  --sandbox read-only
  --skip-git-repo-check
  --output-last-message <temporary-file>
  -
```

`--ignore-user-config` 防止用户的项目或全局配置改变测试行为，但仍使用现有 Codex 身份验证。沙盒固定为只读，不开放网络、审批、沙盒或其他任意 CLI 参数的界面配置。

模型默认为 `gpt-6-astra`，允许输入其他模型标识；推理强度默认为 `low`，仅允许 `low`、`medium`、`high` 和 `xhigh`。每道挑战超时为 120 秒。超时时终止子进程树；无论成功或失败都删除临时输出文件。

Codex 的最终回答从 `--output-last-message` 指定的文件读取。空回答、非零退出、超时或未登录都转换为简短的中文错误，不将完整内部日志或可能的凭据返回给页面。

## HTTP 接口

### `POST /api/codex/status`

请求：

```json
{
  "codex_path": "C:\\optional\\path\\codex.exe"
}
```

`codex_path` 可省略或为空，此时启用自动发现。成功响应：

```json
{
  "available": true,
  "authenticated": true,
  "path": "C:\\...\\codex.exe",
  "source": "desktop",
  "version": "0.162.0-alpha.17.2"
}
```

未就绪时仍返回结构化状态，并通过 `error` 给出原因。非 Windows 环境直接报告不支持。

### `POST /api/test/codex/probe`

请求：

```json
{
  "codex_path": "C:\\optional\\path\\codex.exe",
  "model": "gpt-6-astra",
  "reasoning_effort": "low",
  "prompt": "...",
  "expected_count": 311
}
```

返回字段与现有 `/api/test/probe` 的成功响应保持一致：

```json
{
  "text": "...",
  "parsed_numbers": 311,
  "minimum_numbers": 172,
  "accepted": true
}
```

输入字段缺失或不合法返回 HTTP 400；Codex 不可用或未登录返回 HTTP 503；CLI 执行失败或超时返回 HTTP 502。一道挑战失败不终止整次自动测试，前端继续尝试下一道。

## 前端交互

“Codex 自动测试”页签与现有 API 页签同级。表单包含：

- Codex 路径：可留空以自动检测，也可粘贴完整 `codex.exe` 路径。自动检测成功后，输入框回填实际选中的完整路径，不只显示“检测成功”。
- 运行时状态：显示路径来源（如“Codex 桌面版”或“手动指定”）、版本及登录状态，并提供“自动检测”按钮。点击该按钮时忽略当前输入值，重新执行自动发现并回填新结果。
- 模型：自由文本输入，默认 `gpt-6-astra`。
- 推理强度：下拉选择，默认 `low`。
- “开始测试”按钮。

浏览器使用 `localStorage` 保存用户手动指定且成功使用的 Codex 路径，以及最后使用的模型和推理强度。自动发现的路径会在当前页面明确回填，但不作为手动覆盖路径持久化，以便桌面版升级后下次仍能发现最新版本。服务器不将这些配置写入仓库或其他持久化文件。

将现有 `testViaApi` 中的调度逻辑抽取为通用自动测试运行器。它接收 probe URL、请求配置和进度 DOM 引用，但保持现有行为：两批各三道挑战、顺序执行、三份有效回答后停止、最少一份有效回答才进入归因。API 和 Codex 页签各自有进度容器，共用渲染函数。

结果区的自动测试说明根据传输类型显示“API”或“Codex CLI”，其他归因结果结构不变。

## 安全与稳定性

- 仅执行通过校验的 `codex.exe`，不使用 shell 或字符串命令拼接。
- 模型和推理强度映射到固定参数位置，推理强度使用白名单。
- 挑战文本只走标准输入，不参与命令行构造。
- 运行时固定为临时会话和只读沙盒，避免修改工作区。
- 超时和所有错误路径都必须回收子进程及临时文件。
- 页面不接收、显示或保存 Codex 认证凭据。
- Flask 应用继续默认绑定 `127.0.0.1`。如用户自行将服务暴露到远程网络，Codex 执行接口不视为安全的多用户服务。

## 错误处理

界面显示可操作的错误信息：

- 找不到 CLI：提示启动 Codex 桌面版或手动填写 `codex.exe` 路径。
- 路径无效：说明文件不存在、不是 `codex.exe` 或版本检查失败。
- 未登录：提示在 Codex 桌面版或 CLI 中完成登录。
- 模型不可用：显示 CLI 返回的简化原因，并将当前挑战标记为失败。
- 超时：标记当前挑战超过 120 秒，回收进程后继续下一道挑战。
- 数字不足：沿用 API 自动测试的门槛和展示方式。

页面保留每次失败的简短摘要，最后在自动测试说明中显示失败次数。只要存在至少一份有效回答，仍允许进行归因。

## 指纹库合并隔离

Codex 功能不修改以下文件：

- `fingerprint.py`
- `bank_builder.py`
- `challenge_suite.py`
- `data/*_bank.json`
- `data/*_reference.jsonl`
- `data/unified_bank.json`
- `static/data/unified_bank.json`
- `codex-plugin/modeltrace-guard/assets/unified_bank.json`

主要新代码位于独立的 `codex_runner.py`、`codex_routes.py`、`automatic_testing.py` 和相应测试文件。`app.py` 只增加 Blueprint 注册和对通用 probe 评估函数的调用。因此，其他分支只新增指纹数据或调整建库算法时，不会与此功能发生文本或逻辑冲突。只有同时修改测试页签、通用自动测试流程或 `app.py` 相邻代码时，才可能需要小量手工合并。

## 测试策略

使用 Python 标准库 `unittest`，不为此功能增加生产依赖。所有行为在实现前先写失败测试。

单元测试覆盖：

- 手动路径、环境变量、桌面版目录、安装目录和 PATH 的发现优先级。
- 桌面版存在多个版本时选择最新的可用版本。
- 无效文件名、不存在路径、非 Windows 环境、版本检查失败和未登录。
- Codex 命令参数、prompt 标准输入、最终回答文件读取和临时文件回收。
- 成功、空输出、非零退出和超时路径。
- API 与 Codex probe 对同一输出得到完全相同的数字数量与是否达标结果。

Flask 接口测试覆盖：

- Codex 状态接口的就绪、未登录和无可执行文件响应。
- Codex probe 的 200、400、502 和 503 响应。
- 首页包含第三个页签、默认模型与推理强度。
- 现有 API probe 保持原有响应契约。

手工集成验证在当前 Windows 环境中进行：

1. 不填路径，确认自动选中 Codex 桌面版内置 CLI。
2. 确认页面显示版本和已登录状态。
3. 使用 `gpt-6-astra` 和 `low` 完成至少一道真实挑战。
4. 确认有效数字被识别，页面进度正常更新，最终归因结果可显示。
5. 对一个无效路径验证可操作的错误提示。

## 验收标准

- Windows 本机页面显示三个测试页签，切换不影响现有手动和 API 测试。
- 无手工路径时能优先检测 Codex 桌面版 `codex.exe`，将实际选中的完整路径回填到输入框，并显示路径来源、版本和登录状态。
- 手动填写的有效 `codex.exe` 路径能覆盖自动发现结果。
- `gpt-6-astra` 能通过 Codex CLI 完成真实 probe，输出使用与 API 测试相同的解析和门槛。
- 测试仍以三份有效输出为目标、最多尝试六次，并通过统一指纹库进行归因。
- CLI 不可用、未登录、执行失败、超时和数字不足均有明确页面反馈，不泄露凭据或完整内部日志。
- 新增和现有自动化测试全部通过。
- Git diff 不包含指纹算法、指纹原始数据或生成的指纹库变更。
