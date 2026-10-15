import {
  collectAutomaticOutputs,
  readCodexPreferences,
  writeCodexPreferences,
} from "./automatic-test-core.mjs";

const state = {
  challenges: [],
  bankId: window.DEFAULT_BANK_ID,
  bank: window.BANK_SUMMARIES[window.DEFAULT_BANK_ID],
  unified: window.UNIFIED_SUMMARY,
};

const byId = (id) => document.getElementById(id);
let codexInitialized = false;
let codexManualPath = false;
let codexStatusBusy = false;
let automaticTesting = false;

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
  if (group === "test" && name === "codex" && !codexInitialized) initializeCodex();
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
  if (!response.ok) throw new Error(result.error || "请求失败");
  return result;
}

function saveCodexPreferences() {
  try {
    writeCodexPreferences(window.localStorage, {
      manualPath: codexManualPath ? byId("codex-path").value.trim() : "",
      model: byId("codex-model").value.trim(),
      reasoningEffort: byId("codex-reasoning-effort").value,
    });
  } catch {
    // The test remains usable when browser storage is unavailable.
  }
}

function updateAutomaticControls() {
  document.querySelectorAll("#api-test-form button[type=submit], #codex-test-form input, #codex-test-form select, #codex-test-form button")
    .forEach((element) => { element.disabled = automaticTesting || (codexStatusBusy && element.closest("#codex-test-form")); });
}

async function detectCodex(path, manual) {
  if (codexStatusBusy) return false;
  codexStatusBusy = true;
  updateAutomaticControls();
  setMessage(byId("codex-runtime-status"), "正在检查 Codex 路径、版本和登录状态……", "working");
  try {
    const status = await requestJson("/api/codex/status", { codex_path: path });
    const sources = { desktop: "桌面版", install: "安装目录", environment: "环境变量", path: "PATH", manual: "手动路径" };
    if (status.available) {
      byId("codex-path").value = status.path;
      codexManualPath = manual;
    }
    const details = status.available
      ? `来源：${sources[status.source] || status.source} · 版本：${status.version} · 登录：${status.authenticated ? "已登录" : "未登录"}`
      : "";
    if (!status.available || !status.authenticated) {
      setMessage(byId("codex-runtime-status"), `${details}${details ? "。" : ""}${status.error || "Codex 不可用"}。请检查完整 codex.exe 路径，或点击自动检测；未登录时请先在 Codex 中登录。`, "error");
      return false;
    }
    setMessage(byId("codex-runtime-status"), details, "success");
    saveCodexPreferences();
    return true;
  } catch (error) {
    setMessage(byId("codex-runtime-status"), `无法检查 Codex：${error.message}。请重试自动检测或检查路径。`, "error");
    return false;
  } finally {
    codexStatusBusy = false;
    updateAutomaticControls();
  }
}

function initializeCodex() {
  codexInitialized = true;
  let preferences;
  try {
    preferences = readCodexPreferences(window.localStorage);
  } catch {
    preferences = readCodexPreferences(null);
  }
  byId("codex-path").value = preferences.manualPath;
  byId("codex-model").value = preferences.model;
  byId("codex-reasoning-effort").value = preferences.reasoningEffort;
  codexManualPath = Boolean(preferences.manualPath);
  return detectCodex(preferences.manualPath, codexManualPath);
}

async function testAutomatically(event, options) {
  event.preventDefault();
  if (automaticTesting || (options.beforeRun && codexStatusBusy)) return;
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
  beforeRun: () => detectCodex(codexManualPath ? byId("codex-path").value.trim() : "", codexManualPath),
  configuration: () => ({
    codex_path: byId("codex-path").value.trim(), model: byId("codex-model").value.trim(),
    reasoning_effort: byId("codex-reasoning-effort").value,
  }),
  onSuccess: saveCodexPreferences,
}));
byId("codex-detect").addEventListener("click", () => {
  codexManualPath = false;
  saveCodexPreferences();
  return detectCodex("", false);
});
byId("codex-path").addEventListener("input", () => { codexManualPath = Boolean(byId("codex-path").value.trim()); });
byId("codex-path").addEventListener("blur", (event) => {
  // Let the clicked button run its own discovery/preflight before disabling it.
  if (event.relatedTarget?.closest("#codex-test-form button")) return;
  if (!automaticTesting && codexManualPath) detectCodex(byId("codex-path").value.trim(), true);
});
byId("auto-enrollment").addEventListener("submit", enrollAutomatically);
byId("show-create-bank").addEventListener("click", () => { byId("create-bank-form").hidden = !byId("create-bank-form").hidden; });
byId("create-bank-form").addEventListener("submit", createBank);

renderInventory();
loadChallenges();
