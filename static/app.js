import {
  collectAutomaticOutputs,
  readCodexPreferences,
  writeCodexPreferences,
} from "./automatic-test-core.mjs";
import {
  runCandyBatch,
  summarizeCandyResults,
  validateCandySettings,
} from "./candy-test-core.mjs";

const state = {
  challenges: [],
  bankId: window.DEFAULT_BANK_ID,
  bank: window.BANK_SUMMARIES[window.DEFAULT_BANK_ID],
  unified: window.UNIFIED_SUMMARY,
  candyQuestion: null,
  candyBatch: null,
};

const byId = (id) => document.getElementById(id);
let automaticTesting = false;
let candyPreparing = false;
let candyTesting = false;
let candyStopRequested = false;

const codexUis = {
  test: {
    initialized: false, manualPath: false, statusBusy: false, modelsBusy: false,
    path: "codex-path", model: "codex-model", reasoning: "codex-reasoning-effort",
    useUserConfig: "codex-use-user-config", detect: "codex-detect",
    modelToggle: "codex-model-toggle", modelRefresh: "codex-model-refresh",
    modelMenu: "codex-model-menu", modelStatus: "codex-model-status",
    runtimeStatus: "codex-runtime-status", form: "codex-test-form",
  },
  candy: {
    initialized: false, manualPath: false, statusBusy: false, modelsBusy: false,
    path: "candy-codex-path", model: "candy-codex-model", reasoning: "candy-codex-reasoning-effort",
    useUserConfig: "candy-codex-use-user-config", detect: "candy-codex-detect",
    modelToggle: "candy-codex-model-toggle", modelRefresh: "candy-codex-model-refresh",
    modelMenu: "candy-codex-model-menu", modelStatus: "candy-codex-model-status",
    runtimeStatus: "candy-codex-runtime-status", form: "candy-codex-form",
  },
};

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

function percent(value) {
  return `${(value * 100).toFixed(1)}%`;
}

function optionalNumber(id) {
  const value = byId(id).value.trim();
  return value === "" ? null : Number(value);
}

function setMessage(element, text, type = "error") {
  element.textContent = text;
  element.className = `message ${type}`;
  element.hidden = !text;
}

function activateWorkspace(name) {
  document.querySelectorAll(".workspace").forEach((item) => item.classList.toggle("active", item.id === `workspace-${name}`));
  document.querySelectorAll("[data-workspace]").forEach((item) => item.classList.toggle("active", item.dataset.workspace === name));
}

function activateMode(group, name) {
  document.querySelectorAll(`[data-${group}-mode]`).forEach((item) => item.classList.toggle("active", item.dataset[`${group}Mode`] === name));
  document.querySelectorAll(`#workspace-${group === "test" ? "test" : "library"} .mode-panel`).forEach((item) => {
    item.classList.toggle("active", item.id === `${group}-${name}` || item.id === `library-${name}`);
  });
  if (group === "test" && name === "codex" && !codexUis.test.initialized) initializeCodex("test");
}

function activateCandyMode(name) {
  document.querySelectorAll("[data-candy-mode]").forEach((item) => item.classList.toggle("active", item.dataset.candyMode === name));
  document.querySelectorAll("#workspace-candy .mode-panel").forEach((item) => item.classList.toggle("active", item.id === `candy-${name}`));
  if (name === "codex" && !codexUis.candy.initialized) initializeCodex("candy");
}

async function loadChallenges() {
  byId("regenerate").disabled = true;
  byId("result").hidden = true;
  setMessage(byId("test-message"), "");
  const response = await fetch("/api/challenges");
  state.challenges = (await response.json()).challenges;
  renderChallenges();
  byId("regenerate").disabled = false;
}

function renderChallenges() {
  byId("challenge-list").innerHTML = state.challenges.map((challenge, index) => `
    <article class="challenge-item">
      <div class="challenge-header">
        <strong>挑战 ${index + 1}</strong>
        <span>${challenge.expected_count} 个数字</span>
        <button type="button" data-copy="${index}">复制提示词</button>
      </div>
      <div class="challenge-columns">
        <div><label>发送给待测模型</label><pre>${escapeHtml(challenge.prompt)}</pre></div>
        <div><label for="output-${index}">粘贴完整输出</label><textarea id="output-${index}" spellcheck="false" placeholder="保留文字、标点、代码块和完整数字序列"></textarea></div>
      </div>
    </article>
  `).join("");
  document.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", async () => {
      await navigator.clipboard.writeText(state.challenges[Number(button.dataset.copy)].prompt);
      button.textContent = "已复制";
      window.setTimeout(() => { button.textContent = "复制提示词"; }, 1000);
    });
  });
}

function renderResult(payload) {
  const diagnostics = payload.diagnostics.map((item, index) => `
    <span class="diagnostic ${item.accepted ? "accepted" : "rejected"}">挑战 ${index + 1}: ${item.parsed_numbers} 个数字 · ${item.accepted ? "计入" : "忽略"}</span>
  `).join("");
  const rows = payload.results.map((item, index) => `
    <tr class="${index === 0 ? "winner" : ""}">
      <td>${index + 1}</td><td><strong>${escapeHtml(item.display_name)}</strong></td><td>${escapeHtml(item.family_name)}</td>
      <td><div class="probability-cell"><span><i style="width:${item.probability * 100}%"></i></span><strong>${percent(item.probability)}</strong></div></td>
      <td>${percent(item.profile_similarity)}</td>
    </tr>
  `).join("");
  const automatic = payload.automatic_test || (payload.api_test && { transport: "API", ...payload.api_test });
  const automaticErrors = automatic ? normalizeAutomaticErrors(automatic.errors) : [];
  const failureDetails = automaticErrors
    .map((error) => `挑战 ${escapeHtml(error.attempt)}：${escapeHtml(error.message)}`)
    .join("；");
  const automaticNote = automatic
    ? `<span>${escapeHtml(automatic.transport)} 获得 ${automatic.received}/${automatic.requested} 份有效回答，实际尝试 ${automatic.attempted}/${automatic.max_attempts}${automaticErrors.length ? `，${automaticErrors.length} 次未采用` : ""}${failureDetails ? `。失败摘要：${failureDetails}` : ""}</span>`
    : "";
  byId("result").innerHTML = `
    <div class="result-summary">
      <div><span>最可能模型</span><strong>${escapeHtml(payload.prediction_name)}</strong></div>
      <div><span>统一库概率</span><strong>${percent(payload.probability)}</strong></div>
      <div><span>自动识别家族</span><strong>${escapeHtml(payload.family_prediction_name)} · ${percent(payload.family_probability)}</strong></div>
      <div><span>有效查询</span><strong>${payload.used_outputs}/3</strong></div>
    </div>
    <div class="diagnostics">${diagnostics}</div>
    <div class="table-wrap"><table><thead><tr><th>排序</th><th>候选模型</th><th>家族</th><th>归因概率</th><th>分布相似度</th></tr></thead><tbody>${rows}</tbody></table></div>
    ${automaticNote ? `<div class="result-note">${automaticNote}</div>` : ""}
    <div class="result-guidance" role="note" aria-label="结果说明">
      <p>本工具仅对指纹库内的模型进行归因；若待测模型不在指纹库中，得到任何结果都有可能。</p>
      <p>Claude Code 的系统提示词会影响模型偏好，测试结果存在较大偏差，建议不要在 Claude Code 中测试。</p>
    </div>
  `;
  byId("result").hidden = false;
  byId("result").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function analyzeManual() {
  const button = byId("analyze");
  button.disabled = true;
  setMessage(byId("test-message"), "正在计算……", "working");
  const outputs = state.challenges.map((challenge, index) => ({
    text: byId(`output-${index}`).value,
    expected_count: challenge.expected_count,
  }));
  const response = await fetch("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ outputs }) });
  const payload = await response.json();
  if (response.ok) {
    setMessage(byId("test-message"), "");
    renderResult(payload);
  } else {
    setMessage(byId("test-message"), payload.error || "无法完成归因。", "error");
    byId("result").hidden = true;
  }
  button.disabled = false;
}

function normalizeAutomaticErrors(errors) {
  return Array.isArray(errors) ? errors.map((error, index) => (
    error && typeof error === "object"
      ? { attempt: error.attempt, message: error.message }
      : { attempt: index + 1, message: String(error) }
  )) : [];
}

function failureSummaryText(errors) {
  return normalizeAutomaticErrors(errors)
    .map((error) => `挑战 ${error.attempt}：${error.message}`)
    .join("；");
}

function renderAutomaticProgress(ids, states, errors, status) {
  const valid = states.filter((state) => state === "done").length;
  const attempted = states.filter((state) => ["done", "invalid", "error"].includes(state)).length;
  const target = 3;
  const errorsByAttempt = new Map(
    normalizeAutomaticErrors(errors).map((error) => [Number(error.attempt), error.message]),
  );
  byId(ids.panel).hidden = false;
  byId(ids.status).textContent = status;
  byId(ids.count).textContent = `有效 ${valid}/${target} · 已尝试 ${attempted}/${states.length}`;
  byId(ids.fill).style.width = `${(valid / target) * 100}%`;
  byId(ids.steps).innerHTML = states.map((state, index) => {
    const labels = { pending: "等待", working: "请求中", done: "有效", invalid: "数字不足", error: "请求失败", skipped: "无需调用" };
    const failure = errorsByAttempt.get(index + 1);
    return `<span class="progress-step ${state}"><b>${index + 1}</b>挑战 ${index + 1} · ${labels[state]}${failure ? ` · ${escapeHtml(failure)}` : ""}</span>`;
  }).join("");
}

async function requestJson(url, payload) {
  const response = await fetch(url, payload === undefined ? undefined : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(result.error || "请求失败");
    error.status = response.status;
    throw error;
  }
  return result;
}

function saveCodexPreferences(kind = "test") {
  const ui = codexUis[kind];
  try {
    writeCodexPreferences(window.localStorage, {
      manualPath: ui.manualPath ? byId(ui.path).value.trim() : "",
      model: byId(ui.model).value.trim(),
      reasoningEffort: byId(ui.reasoning).value,
      useUserConfig: byId(ui.useUserConfig).checked,
    });
  } catch {
    // The test remains usable when browser storage is unavailable.
  }
}

function updateAutomaticControls() {
  document.querySelectorAll("#api-test-form button[type=submit], #codex-test-form input, #codex-test-form select, #codex-test-form button")
    .forEach((element) => {
      element.disabled = automaticTesting || candyPreparing || candyTesting
        || (codexUis.test.statusBusy && element.closest("#codex-test-form"))
        || (codexUis.test.modelsBusy && [codexUis.test.useUserConfig, codexUis.test.modelToggle, codexUis.test.modelRefresh].includes(element.id));
    });
  document.querySelectorAll("#candy-api-form input, #candy-api-form select, #candy-api-form button, #candy-codex-form input, #candy-codex-form select, #candy-codex-form button")
    .forEach((element) => {
      element.disabled = candyPreparing || candyTesting || automaticTesting
        || (codexUis.candy.statusBusy && element.closest("#candy-codex-form"))
        || (codexUis.candy.modelsBusy && [codexUis.candy.useUserConfig, codexUis.candy.modelToggle, codexUis.candy.modelRefresh].includes(element.id));
    });
  byId("candy-stop").disabled = !candyTesting || candyStopRequested;
}

async function loadCodexModels(kind = "test") {
  const ui = codexUis[kind];
  if (ui.modelsBusy) return false;
  ui.modelsBusy = true;
  updateAutomaticControls();
  const status = byId(ui.modelStatus);
  status.hidden = false;
  status.textContent = "正在加载模型列表……";
  try {
    const result = await requestJson("/api/codex/models", {
      codex_path: byId(ui.path).value.trim(),
      use_user_config: byId(ui.useUserConfig).checked,
    });
    byId(ui.modelMenu).innerHTML = result.models.map((model) => {
      const label = model.label === model.id ? "" : `<small>${escapeHtml(model.label)}</small>`;
      return `<button class="codex-model-item" type="button" role="option" data-model-id="${escapeHtml(model.id)}"><span>${escapeHtml(model.id)}</span>${label}</button>`;
    }).join("");
    status.textContent = result.models.length
      ? `已加载 ${result.models.length} 个模型；仍可手动输入其他模型。`
      : "未发现可选模型；仍可手动输入模型。";
    return true;
  } catch (error) {
    status.textContent = `模型列表加载失败：${error.message}；仍可手动输入模型。`;
    return false;
  } finally {
    ui.modelsBusy = false;
    updateAutomaticControls();
  }
}

async function detectCodex(path, manual, refreshModels = false, kind = "test") {
  const ui = codexUis[kind];
  if (ui.statusBusy) return false;
  ui.statusBusy = true;
  updateAutomaticControls();
  setMessage(byId(ui.runtimeStatus), "正在检查 Codex 路径、版本和登录状态……", "working");
  try {
    const status = await requestJson("/api/codex/status", { codex_path: path });
    const sources = { desktop: "桌面版", install: "安装目录", environment: "环境变量", path: "PATH", manual: "手动路径" };
    if (status.available) {
      byId(ui.path).value = status.path;
      ui.manualPath = manual;
    }
    const details = status.available
      ? `来源：${sources[status.source] || status.source} · 版本：${status.version} · 登录：${status.authenticated ? "已登录" : "未登录"}`
      : "";
    if (!status.available || !status.authenticated) {
      setMessage(byId(ui.runtimeStatus), `${details}${details ? "。" : ""}${status.error || "Codex 不可用"}`, "error");
      return false;
    }
    setMessage(byId(ui.runtimeStatus), details, "success");
    if (refreshModels) await loadCodexModels(kind);
    saveCodexPreferences(kind);
    return true;
  } catch (error) {
    setMessage(byId(ui.runtimeStatus), error.message, "error");
    return false;
  } finally {
    ui.statusBusy = false;
    updateAutomaticControls();
  }
}

function initializeCodex(kind = "test") {
  const ui = codexUis[kind];
  ui.initialized = true;
  let preferences;
  try {
    preferences = readCodexPreferences(window.localStorage);
  } catch {
    preferences = readCodexPreferences(null);
  }
  byId(ui.path).value = preferences.manualPath;
  byId(ui.model).value = preferences.model;
  byId(ui.reasoning).value = preferences.reasoningEffort;
  byId(ui.useUserConfig).checked = preferences.useUserConfig;
  ui.manualPath = Boolean(preferences.manualPath);
  return detectCodex(preferences.manualPath, ui.manualPath, true, kind);
}

async function testAutomatically(event, options) {
  event.preventDefault();
  if (automaticTesting || candyPreparing || candyTesting || (options.beforeRun && codexUis.test.statusBusy)) return;
  automaticTesting = true;
  updateAutomaticControls();
  byId("result").hidden = true;
  setMessage(byId("test-message"), "");
  try {
    if (options.beforeRun && !await options.beforeRun()) return;
    const firstBatch = (await requestJson("/api/challenges")).challenges;
    const challenges = firstBatch.concat((await requestJson("/api/challenges")).challenges);
    const { outputs, errors, states, attempted } = await collectAutomaticOutputs({
      challenges,
      configuration: options.configuration(),
      target: 3,
      probe: (payload) => requestJson(options.endpoint, payload),
      onProgress: ({ states, errors, status }) => renderAutomaticProgress(options.progressIds, states, errors, status),
    });
    if (!outputs.length) {
      setMessage(byId("test-message"), `没有获得可分析输出。${errors.length} 次未采用。${failureSummaryText(errors)}`, "error");
      return;
    }
    if (options.onSuccess) options.onSuccess();
    renderAutomaticProgress(options.progressIds, states, errors, "模型回答已收齐，正在计算归因概率……");
    const result = await requestJson("/api/analyze", { outputs });
    result.automatic_test = { transport: options.transport, requested: 3, attempted, max_attempts: challenges.length, received: outputs.length, errors };
    renderAutomaticProgress(options.progressIds, states, errors, `测试完成：${outputs.length}/3 份有效回答进入归因`);
    renderResult(result);
  } catch (error) {
    setMessage(byId("test-message"), `${options.transport} 自动测试失败：${error.message}`, "error");
  } finally {
    automaticTesting = false;
    updateAutomaticControls();
  }
}

async function loadCandyQuestion() {
  try {
    const question = await requestJson("/api/candy/question");
    state.candyQuestion = question;
    byId("candy-question-prompt").textContent = question.prompt;
    return question;
  } catch (error) {
    byId("candy-question-prompt").textContent = "题目加载失败";
    setMessage(byId("candy-message"), error.message, "error");
    return null;
  }
}

function candyInteger(id) {
  const raw = byId(id).value.trim();
  return /^\d+$/.test(raw) ? Number(raw) : Number.NaN;
}

function candyStatusLabel(status) {
  return ({
    pending: "等待中", running: "执行中", correct: "正确", incorrect: "错误",
    ungraded: "待判定", error: "调用失败", not_run: "未执行",
  })[status] || status;
}

function candyValue(value, suffix = "") {
  return value === null || value === undefined ? "未提供" : `${value}${suffix}`;
}

function candyElapsed(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "未提供";
  return `${Number(value.toFixed(3))} 秒`;
}

function renderCandyProgress(snapshot) {
  const planned = snapshot.plannedRounds || 0;
  const summary = summarizeCandyResults(snapshot.results, planned);
  byId("candy-progress-panel").hidden = false;
  byId("candy-progress-status").textContent = candyTesting
    ? (candyStopRequested ? "当前轮结束后停止" : `正在执行第 ${Math.min(snapshot.completedRounds + 1, planned)} 轮`)
    : "测试完成";
  byId("candy-progress-count").textContent = `已完成 ${summary.completedRounds}/${planned} · 未执行 ${summary.counts.not_run}`;
  byId("candy-progress-fill").style.width = planned ? `${(summary.completedRounds / planned) * 100}%` : "0%";
  renderCandyResults(snapshot.results, summary);
}

function renderCandyResults(results, summary) {
  const rate = summary.correctRate === null
    ? "未提供"
    : `${(summary.correctRate * 100).toFixed(1)}%（${summary.counts.correct}/${summary.gradedRounds}）`;
  byId("candy-summary").textContent = [
    `计划轮数 ${summary.plannedRounds}`,
    `已完成 ${summary.completedRounds}/${summary.plannedRounds}`,
    `未执行 ${summary.counts.not_run}`,
    `可判定 ${summary.gradedRounds}`,
    `正确 ${summary.counts.correct}`,
    `错误 ${summary.counts.incorrect}`,
    `待判定 ${summary.counts.ungraded}`,
    `调用失败 ${summary.counts.error}`,
    `正确率 ${rate}`,
  ].join(" · ");
  byId("candy-result-rows").innerHTML = results.map((item) => {
    const answer = item.answer || item.error || "未提供";
    const statusClass = item.status === "correct" ? "ok" : item.status === "incorrect" || item.status === "error" ? "error" : "warning";
    return `<tr>
      <td>${item.round}</td>
      <td><span class="status-tag ${statusClass}">${escapeHtml(candyStatusLabel(item.status))}</span></td>
      <td>${candyValue(item.final_answer)}</td>
      <td>${candyValue(item.usage?.input_tokens)}</td>
      <td>${candyValue(item.usage?.output_tokens)}</td>
      <td>${candyValue(item.usage?.reasoning_tokens)}</td>
      <td>${candyElapsed(item.elapsed_seconds)}</td>
      <td>${candyValue(item.tps)}</td>
      <td>${escapeHtml(item.grading_reason || item.error || "未提供")}</td>
      <td><details class="candy-answer-disclosure"><summary>查看回答</summary><pre>${escapeHtml(answer)}</pre></details></td>
    </tr>`;
  }).join("");
  byId("candy-results").hidden = false;
}

function candyConfiguration(kind) {
  const rounds = candyInteger(`candy-${kind}-rounds`);
  const timeoutSeconds = candyInteger(`candy-${kind}-timeout`);
  const validation = validateCandySettings({ rounds, timeoutSeconds });
  if (!validation.valid) throw new Error("测试轮数或请求超时超出允许范围");
  if (kind === "api") {
    const baseUrl = byId("candy-api-base").value.trim();
    const apiKey = byId("candy-api-key").value.trim();
    const apiModel = byId("candy-api-model").value.trim();
    const apiFormat = byId("candy-api-format").value;
    if (!baseUrl || !apiKey || !apiModel || !["openai", "anthropic"].includes(apiFormat)) {
      throw new Error("请完整填写 API 配置");
    }
    let parsedBaseUrl;
    try {
      parsedBaseUrl = new URL(baseUrl);
    } catch {
      throw new Error("Base URL 必须是有效的 HTTP 或 HTTPS 地址");
    }
    if (!["http:", "https:"].includes(parsedBaseUrl.protocol) || !parsedBaseUrl.hostname
      || parsedBaseUrl.username || parsedBaseUrl.password) {
      throw new Error("Base URL 必须是有效的 HTTP 或 HTTPS 地址");
    }
    return {
      rounds, timeoutSeconds,
      summary: `API · ${apiModel} · ${apiFormat}`,
      endpoint: "/api/candy/api/probe",
      payload: {
        base_url: baseUrl, api_key: apiKey, api_model: apiModel, api_format: apiFormat,
        temperature: optionalNumber("candy-api-temperature"),
      },
    };
  }
  const model = byId("candy-codex-model").value.trim();
  if (!/^[A-Za-z0-9._/:-]{1,128}$/.test(model)) {
    throw new Error("Codex 模型必须是有效的模型标识，最多 128 个字符");
  }
  return {
    rounds, timeoutSeconds,
    summary: `Codex CLI · ${model} · ${byId("candy-codex-reasoning-effort").value}`,
    endpoint: "/api/candy/codex/probe",
    payload: {
      codex_path: byId("candy-codex-path").value.trim(), model,
      reasoning_effort: byId("candy-codex-reasoning-effort").value,
      use_user_config: byId("candy-codex-use-user-config").checked,
    },
  };
}

async function startCandyBatch(event, kind) {
  event.preventDefault();
  if (candyPreparing || candyTesting || automaticTesting) return;
  let configuration;
  try {
    configuration = candyConfiguration(kind);
  } catch (error) {
    setMessage(byId("candy-message"), error.message, "error");
    return;
  }
  candyPreparing = true;
  updateAutomaticControls();
  let enteredRun = false;
  let protocolError = "";
  try {
    if (kind === "codex") {
      const ui = codexUis.candy;
      if (ui.statusBusy || !await detectCodex(ui.manualPath ? byId(ui.path).value.trim() : "", ui.manualPath, false, "candy")) return;
      configuration.payload.codex_path = byId(ui.path).value.trim();
      saveCodexPreferences("candy");
    }
    const question = await loadCandyQuestion();
    if (!question) return;
    if (!candyPreparing || automaticTesting || candyTesting) return;

    const questionSnapshot = { ...question };
    candyPreparing = false;
    candyTesting = true;
    enteredRun = true;
    candyStopRequested = false;
    state.candyBatch = {
      kind, question: questionSnapshot, configuration: configuration.summary,
      plannedRounds: configuration.rounds, results: [], summary: null,
    };
    setMessage(byId("candy-message"), "");
    byId("candy-batch-title").textContent = `${kind === "api" ? "API" : "Codex"} 糖果测试`;
    byId("candy-batch-config").textContent = configuration.summary;
    byId("candy-batch-question").textContent = questionSnapshot.prompt;
    byId("candy-results").hidden = false;
    updateAutomaticControls();

    const outcome = await runCandyBatch({
      rounds: configuration.rounds,
      shouldStop: () => candyStopRequested,
      onUpdate: renderCandyProgress,
      probe: async () => {
        try {
          return await requestJson(configuration.endpoint, {
            ...configuration.payload,
            question_id: questionSnapshot.question_id,
            timeout_seconds: configuration.timeoutSeconds,
          });
        } catch (error) {
          if (error.status === 409) {
            state.candyQuestion = null;
            candyStopRequested = true;
          }
          if (error.status === 400) candyStopRequested = true;
          if (error.status === 400 || error.status === 409) protocolError = error.message;
          throw error;
        }
      },
    });
    state.candyBatch.results = outcome.results;
    state.candyBatch.summary = outcome.summary;
    renderCandyResults(outcome.results, outcome.summary);
    if (protocolError) setMessage(byId("candy-message"), protocolError, "error");
  } finally {
    candyPreparing = false;
    if (enteredRun) candyTesting = false;
    updateAutomaticControls();
    const summary = state.candyBatch?.summary;
    if (summary) {
      byId("candy-progress-status").textContent = candyStopRequested && summary.counts.not_run
        ? "已停止后续测试"
        : "测试完成";
    }
  }
}

function updateUnifiedSummary(summary) {
  state.unified = summary;
  byId("topbar-bank-count").textContent = `${summary.model_count} 个候选模型`;
  byId("active-bank-badge").textContent = `${summary.model_count} 个候选模型`;
}

function renderInventory() {
  byId("selected-bank-name").textContent = state.bank.label;
  byId("model-options").innerHTML = state.bank.models.map((model) => `<option value="${escapeHtml(model.id)}"></option>`).join("");
  byId("bank-inventory").innerHTML = state.bank.models.length
    ? state.bank.models.map((model) => `<span class="fingerprint-item">${escapeHtml(model.display_name)}</span>`).join("")
    : `<span class="empty-inventory">暂无指纹</span>`;
}

async function refreshBank() {
  const response = await fetch(`/api/bank?bank_id=${encodeURIComponent(state.bankId)}`);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "无法读取指纹库");
  state.bank = payload;
  renderInventory();
}

async function selectBank(bankId) {
  state.bankId = bankId;
  await refreshBank();
}

async function enrollAutomatically(event) {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type=submit]");
  button.disabled = true;
  const requested = Number(byId("sample-count").value);
  const started = Date.now();
  const progressTimer = window.setInterval(() => {
    const seconds = Math.floor((Date.now() - started) / 1000);
    setMessage(byId("enrollment-message"), `正在自动识别协议并采集 ${requested} 份回答 · 已等待 ${seconds} 秒`, "working");
  }, 1000);
  setMessage(byId("enrollment-message"), `正在自动识别协议并采集 ${requested} 份回答`, "working");
  let response;
  try {
    response = await fetch("/api/enroll/auto", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        base_url: byId("api-base").value,
        api_key: byId("api-key").value,
        api_model: byId("api-model").value,
        bank_id: state.bankId,
        model_label: byId("auto-model").value,
        sample_count: requested,
        temperature: optionalNumber("temperature"),
      }),
    });
  } catch (error) {
    window.clearInterval(progressTimer);
    setMessage(byId("enrollment-message"), error.message, "error");
    button.disabled = false;
    return;
  }
  window.clearInterval(progressTimer);
  const payload = await response.json();
  if (response.ok) {
    state.bank = payload.bank;
    updateUnifiedSummary(payload.unified);
    renderInventory();
    setMessage(byId("enrollment-message"), `采集完成：收到 ${payload.received}/${payload.requested} 份，${payload.accepted} 份进入指纹库，${payload.rejected} 份无效，${payload.errors.length} 次接口错误。`, "success");
  } else {
    setMessage(byId("enrollment-message"), payload.error || "自动采集失败。", "error");
  }
  button.disabled = false;
}

function renderBankOptions(summaries, selected) {
  byId("bank-select").innerHTML = Object.entries(summaries)
    .map(([bankId, bank]) => `<option value="${escapeHtml(bankId)}"${bankId === selected ? " selected" : ""}>${escapeHtml(bank.label)}</option>`)
    .join("");
}

async function createBank(event) {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type=submit]");
  button.disabled = true;
  const response = await fetch("/api/banks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label: byId("new-bank-name").value }),
  });
  const payload = await response.json();
  if (response.ok) {
    window.BANK_SUMMARIES = payload.banks;
    state.bankId = payload.bank.id;
    state.bank = payload.bank;
    updateUnifiedSummary(payload.unified);
    renderBankOptions(payload.banks, state.bankId);
    renderInventory();
    byId("new-bank-name").value = "";
    byId("create-bank-form").hidden = true;
    setMessage(byId("enrollment-message"), `已创建 ${payload.bank.label}`, "success");
  } else {
    setMessage(byId("enrollment-message"), payload.error || "创建失败。", "error");
  }
  button.disabled = false;
}

document.querySelectorAll("[data-workspace]").forEach((button) => button.addEventListener("click", () => activateWorkspace(button.dataset.workspace)));
document.querySelectorAll("[data-test-mode]").forEach((button) => button.addEventListener("click", () => activateMode("test", button.dataset.testMode)));
document.querySelectorAll("[data-candy-mode]").forEach((button) => button.addEventListener("click", () => activateCandyMode(button.dataset.candyMode)));
byId("bank-select").addEventListener("change", (event) => selectBank(event.target.value));
byId("regenerate").addEventListener("click", loadChallenges);
byId("analyze").addEventListener("click", analyzeManual);
const progressIds = (prefix) => ({
  panel: `${prefix}-test-progress`, status: `${prefix}-progress-status`,
  count: `${prefix}-progress-count`, fill: `${prefix}-progress-fill`, steps: `${prefix}-progress-steps`,
});
byId("api-test-form").addEventListener("submit", (event) => testAutomatically(event, {
  endpoint: "/api/test/probe", transport: "API", progressIds: progressIds("api"),
  configuration: () => ({
    base_url: byId("test-api-base").value, api_key: byId("test-api-key").value,
    api_model: byId("test-api-model").value, temperature: optionalNumber("test-temperature"),
  }),
}));
byId("codex-test-form").addEventListener("submit", (event) => testAutomatically(event, {
  endpoint: "/api/test/codex/probe", transport: "Codex CLI", progressIds: progressIds("codex"),
  beforeRun: () => detectCodex(codexUis.test.manualPath ? byId("codex-path").value.trim() : "", codexUis.test.manualPath),
  configuration: () => ({
    codex_path: byId("codex-path").value.trim(), model: byId("codex-model").value.trim(),
    reasoning_effort: byId("codex-reasoning-effort").value,
    use_user_config: byId("codex-use-user-config").checked,
  }),
  onSuccess: () => saveCodexPreferences("test"),
}));
byId("codex-detect").addEventListener("click", () => {
  codexUis.test.manualPath = false;
  saveCodexPreferences("test");
  return detectCodex("", false, true, "test");
});
byId("codex-model-refresh").addEventListener("click", () => loadCodexModels("test"));
byId("codex-model-toggle").addEventListener("click", () => {
  const menu = byId("codex-model-menu");
  menu.hidden = !menu.hidden;
});
byId("codex-model-menu").addEventListener("click", (event) => {
  const option = event.target.closest("[data-model-id]");
  if (!option) return;
  byId("codex-model").value = option.dataset.modelId;
  byId("codex-model-menu").hidden = true;
});
byId("codex-use-user-config").addEventListener("change", () => loadCodexModels("test"));
byId("codex-path").addEventListener("input", () => { codexUis.test.manualPath = Boolean(byId("codex-path").value.trim()); });
byId("codex-path").addEventListener("blur", (event) => {
  // Let the clicked button run its own discovery/preflight before disabling it.
  if (event.relatedTarget?.closest("#codex-test-form button")) return;
  if (!automaticTesting && !candyTesting && codexUis.test.manualPath) detectCodex(byId("codex-path").value.trim(), true, true, "test");
});
byId("candy-api-form").addEventListener("submit", (event) => startCandyBatch(event, "api"));
byId("candy-codex-form").addEventListener("submit", (event) => startCandyBatch(event, "codex"));
byId("candy-stop").addEventListener("click", () => {
  if (!candyTesting) return;
  candyStopRequested = true;
  byId("candy-progress-status").textContent = "当前轮结束后停止";
  updateAutomaticControls();
});
byId("candy-codex-detect").addEventListener("click", () => {
  codexUis.candy.manualPath = false;
  saveCodexPreferences("candy");
  return detectCodex("", false, true, "candy");
});
byId("candy-codex-model-refresh").addEventListener("click", () => loadCodexModels("candy"));
byId("candy-codex-model-toggle").addEventListener("click", () => {
  const menu = byId("candy-codex-model-menu");
  menu.hidden = !menu.hidden;
});
byId("candy-codex-model-menu").addEventListener("click", (event) => {
  const option = event.target.closest("[data-model-id]");
  if (!option) return;
  byId("candy-codex-model").value = option.dataset.modelId;
  byId("candy-codex-model-menu").hidden = true;
});
byId("candy-codex-use-user-config").addEventListener("change", () => loadCodexModels("candy"));
byId("candy-codex-path").addEventListener("input", () => { codexUis.candy.manualPath = Boolean(byId("candy-codex-path").value.trim()); });
byId("candy-codex-path").addEventListener("blur", (event) => {
  if (event.relatedTarget?.closest("#candy-codex-form button")) return;
  if (!automaticTesting && !candyTesting && codexUis.candy.manualPath) {
    detectCodex(byId("candy-codex-path").value.trim(), true, true, "candy");
  }
});
byId("auto-enrollment").addEventListener("submit", enrollAutomatically);
byId("show-create-bank").addEventListener("click", () => { byId("create-bank-form").hidden = !byId("create-bank-form").hidden; });
byId("create-bank-form").addEventListener("submit", createBank);

renderInventory();
loadChallenges();
loadCandyQuestion();
