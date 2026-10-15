from pathlib import Path
import json
import subprocess
import unittest

from app import app


class TestPageTests(unittest.TestCase):
    def test_page_exposes_independent_candy_workspace_and_controls(self):
        html = app.test_client().get("/").get_data(as_text=True)

        test_position = html.index('data-workspace="test"')
        candy_position = html.index('data-workspace="candy"')
        library_position = html.index('data-workspace="library"')
        self.assertLess(test_position, candy_position)
        self.assertLess(candy_position, library_position)
        self.assertIn('id="workspace-candy"', html)
        self.assertIn('data-candy-mode="api"', html)
        self.assertIn('data-candy-mode="codex"', html)
        self.assertIn('id="candy-question-disclosure"', html)
        self.assertIn('id="candy-question-prompt"', html)
        self.assertIn('id="candy-api-timeout" type="number" min="30" max="1800" value="600"', html)
        self.assertIn('id="candy-codex-timeout" type="number" min="30" max="1800" value="600"', html)
        self.assertIn('id="candy-api-rounds" type="number" min="1" max="50" value="5"', html)
        self.assertIn('id="candy-codex-rounds" type="number" min="1" max="50" value="5"', html)
        self.assertIn('id="candy-stop"', html)
        self.assertIn('id="candy-summary"', html)
        self.assertIn('id="candy-result-rows"', html)
        self.assertIn('id="candy-answer-disclosure"', html)

    def test_model_test_page_offers_codex_automatic_testing(self):
        html = app.test_client().get("/").get_data(as_text=True)

        self.assertIn('data-test-mode="codex"', html)
        self.assertIn('id="test-codex"', html)
        self.assertIn('id="codex-path"', html)
        self.assertIn('value="gpt-6-astra"', html)
        self.assertIn('<option value="low" selected>', html)
        self.assertIn('<input id="codex-use-user-config" type="checkbox">', html)
        self.assertIn('读取 Codex 用户配置（兼容 Codex++）', html)
        self.assertNotIn('list="codex-model-options"', html)
        self.assertNotIn('id="codex-model-options"', html)
        self.assertIn('id="codex-model-toggle"', html)
        self.assertIn('aria-label="展开模型列表"', html)
        self.assertIn('id="codex-model-menu"', html)
        self.assertIn('id="codex-model-refresh"', html)
        self.assertIn('aria-label="刷新模型列表"', html)

    def test_model_test_page_loads_the_automatic_test_module(self):
        html = app.test_client().get("/").get_data(as_text=True)

        self.assertIn('type="module"', html)
        self.assertIn('app.js', html)

    def run_ui_scenario(self, scenario):
        # Execute the real UI module. Only the DOM and HTTP boundaries are doubles;
        # keep the production listeners, busy state, path fill, and persistence real.
        script = r"""
import assert from 'node:assert/strict';
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    id, value: '', checked: false, hidden: false, textContent: '', innerHTML: '',
    _disabled: false, style: {}, dataset: {}, handlers: {},
    get disabled() { return this._disabled; },
    set disabled(value) { this._disabled = Boolean(value); },
    classList: { toggle() {} },
    addEventListener(type, handler) { this.handlers[type] = handler; },
    closest(selector) {
      if (selector === '#codex-test-form button') {
        return ['codex-detect', 'codex-model-toggle', 'codex-model-refresh', 'codex-submit'].includes(id) ? this : null;
      }
      return id.startsWith('codex-') ? element('codex-test-form') : null;
    },
    scrollIntoView() {},
  });
  return elements.get(id);
}
const controls = ['codex-path', 'codex-model', 'codex-reasoning-effort', 'codex-use-user-config',
  'codex-detect', 'codex-model-toggle', 'codex-model-refresh', 'codex-submit', 'api-submit'].map(element);
element('codex-model-menu').hidden = true;
const codexTab = element('codex-mode-tab');
codexTab.dataset.testMode = 'codex';
const saved = new Map();
globalThis.window = {
  DEFAULT_BANK_ID: 'bank', BANK_SUMMARIES: {bank: {label: 'Test', models: []}},
  localStorage: {getItem: key => saved.get(key) ?? null,
    setItem: (key, value) => saved.set(key, value)},
};
globalThis.document = {
  getElementById: element,
  querySelectorAll: selector => selector === '[data-test-mode]' ? [codexTab]
    : selector.startsWith('#api-test-form') ? controls : [],
};
const statusRequests = [];
const modelRequests = [];
let challengeRequests = 0;
let resolveStatus;
globalThis.fetch = async (url, options) => {
  if (url === '/api/challenges') {
    challengeRequests += 1;
    return {ok: true, json: async () => ({challenges: []})};
  }
  if (url === '/api/codex/models') {
    modelRequests.push(JSON.parse(options.body));
    return {ok: true, json: async () => ({models: [
      {id: 'gpt-6-astra', label: 'GPT-6 Astra'},
      {id: 'deepseek-flash', label: 'DeepSeek Flash'},
    ]})};
  }
  assert.equal(url, '/api/codex/status');
  statusRequests.push(JSON.parse(options.body));
  return new Promise(resolve => { resolveStatus = resolve; });
};
await import('./static/app.js');
element('codex-model').value = 'gpt-6-astra';
element('codex-reasoning-effort').value = 'low';
const path = element('codex-path');
const detect = element('codex-detect');
""" + scenario
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def run_automatic_ui_scenario(self, replies, scenario):
        script = r"""
import assert from 'node:assert/strict';
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    id, value: '', checked: false, hidden: true, textContent: '', innerHTML: '', className: '',
    _disabled: false, style: {}, dataset: {}, handlers: {},
    get disabled() { return this._disabled; },
    set disabled(value) { this._disabled = Boolean(value); },
    classList: { toggle() {} },
    addEventListener(type, handler) { this.handlers[type] = handler; },
    closest() { return null; },
    scrollIntoView() {},
  });
  return elements.get(id);
}
const controls = ['codex-path', 'codex-model', 'codex-reasoning-effort', 'codex-use-user-config',
  'codex-detect', 'codex-model-toggle', 'codex-model-refresh', 'codex-submit', 'api-submit'].map(element);
globalThis.window = {
  DEFAULT_BANK_ID: 'bank', BANK_SUMMARIES: {bank: {label: 'Test', models: []}},
  localStorage: {getItem: () => null, setItem() {}},
};
globalThis.document = {
  getElementById: element,
  querySelectorAll: selector => selector.startsWith('#api-test-form') ? controls : [],
};
const challenges = Array.from({length: 3}, (_, index) => ({
  prompt: `prompt-${index + 1}`, expected_count: 100 + index,
}));
let replies = REPLIES;
let analyzed = false;
globalThis.fetch = async (url) => {
  if (url === '/api/challenges') {
    return {ok: true, json: async () => ({challenges})};
  }
  if (url === '/api/test/probe') {
    const reply = replies.shift();
    return {ok: reply.ok, json: async () => reply.payload};
  }
  if (url === '/api/analyze') {
    analyzed = true;
    return {ok: true, json: async () => ({
      diagnostics: [], results: [{display_name: 'Model', family_name: 'Family',
        probability: 1, profile_similarity: 1}], prediction_name: 'Model',
      probability: 1, family_prediction_name: 'Family', family_probability: 1,
      used_outputs: 1,
    })};
  }
  throw new Error(`Unexpected URL: ${url}`);
};
await import('./static/app.js');
await new Promise(resolve => setImmediate(resolve));
""".replace("REPLIES", json.dumps(replies)) + scenario
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def run_candy_ui_scenario(self, scenario):
        script = r"""
import assert from 'node:assert/strict';
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    id, value: '', checked: false, hidden: true, open: false, textContent: '', innerHTML: '', className: '',
    _disabled: false, style: {}, dataset: {}, handlers: {},
    get disabled() { return this._disabled; },
    set disabled(value) { this._disabled = Boolean(value); },
    classList: { toggle() {} },
    addEventListener(type, handler) { this.handlers[type] = handler; },
    closest(selector) {
      if (selector === '#codex-test-form button') return id.startsWith('codex-') ? this : null;
      if (selector === '#candy-codex-form button') return id.startsWith('candy-codex-') ? this : null;
      if (selector === '#codex-test-form') return id.startsWith('codex-') ? element('codex-test-form') : null;
      if (selector === '#candy-codex-form') return id.startsWith('candy-codex-') ? element('candy-codex-form') : null;
      return null;
    },
    scrollIntoView() {},
  });
  return elements.get(id);
}
const modelControls = ['codex-path', 'codex-model', 'codex-reasoning-effort', 'codex-use-user-config',
  'codex-detect', 'codex-model-toggle', 'codex-model-refresh', 'codex-submit', 'api-submit'].map(element);
const candyControls = ['candy-api-base', 'candy-api-key', 'candy-api-model', 'candy-api-format',
  'candy-api-temperature', 'candy-api-rounds', 'candy-api-timeout', 'candy-api-start',
  'candy-codex-path', 'candy-codex-model', 'candy-codex-reasoning-effort',
  'candy-codex-use-user-config', 'candy-codex-detect', 'candy-codex-model-toggle',
  'candy-codex-model-refresh', 'candy-codex-rounds', 'candy-codex-timeout',
  'candy-codex-start'].map(element);
const saved = new Map();
globalThis.window = {
  DEFAULT_BANK_ID: 'bank', BANK_SUMMARIES: {bank: {label: 'Test', models: []}},
  UNIFIED_SUMMARY: {model_count: 0},
  localStorage: {getItem: key => saved.get(key) ?? null, setItem: (key, value) => saved.set(key, value)},
  setTimeout, setInterval, clearInterval,
};
const testNav = element('test-nav'); testNav.dataset.workspace = 'test';
const candyNav = element('candy-nav'); candyNav.dataset.workspace = 'candy';
const libraryNav = element('library-nav'); libraryNav.dataset.workspace = 'library';
const candyApiTab = element('candy-api-tab'); candyApiTab.dataset.candyMode = 'api';
const candyCodexTab = element('candy-codex-tab'); candyCodexTab.dataset.candyMode = 'codex';
globalThis.document = {
  getElementById: element,
  querySelectorAll: selector => {
    if (selector === '[data-workspace]') return [testNav, candyNav, libraryNav];
    if (selector === '[data-test-mode]') return [];
    if (selector === '[data-candy-mode]') return [candyApiTab, candyCodexTab];
    if (selector.startsWith('#api-test-form')) return modelControls;
    if (selector.startsWith('#candy-api-form')) return candyControls;
    return [];
  },
};
const question = {question_id: 'candy-v1', title: '糖果题', prompt: '题目 <final-answer>整数</final-answer>'};
const probePayloads = [];
const probeReplies = [
  {question_id: 'candy-v1', status: 'correct', answer: '过程 <img src=x onerror=alert(1)>\n<final-answer>21</final-answer>', final_answer: 21,
    grading_reason: '答案正确', usage: {input_tokens: 10, output_tokens: 5, reasoning_tokens: 0}, elapsed_seconds: 2.0636650000233203, tps: 2.5, error: null},
  {question_id: 'candy-v1', status: 'ungraded', answer: '没有标签', final_answer: null,
    grading_reason: '缺少最终答案标签', usage: null, elapsed_seconds: 3, tps: null, error: null},
];
globalThis.fetch = async (url, options) => {
  if (url === '/api/challenges') return {ok: true, status: 200, json: async () => ({challenges: []})};
  if (url === '/api/candy/question') return {ok: true, status: 200, json: async () => question};
  if (url === '/api/candy/api/probe') {
    probePayloads.push(JSON.parse(options.body));
    return {ok: true, status: 200, json: async () => probeReplies.shift()};
  }
  throw new Error(`Unexpected URL: ${url}`);
};
await import('./static/app.js');
await new Promise(resolve => setImmediate(resolve));
assert.equal(typeof element('candy-api-form').handlers.submit, 'function', 'candy API form must register a submit handler');
""" + scenario
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_auto_detect_click_is_not_consumed_by_manual_path_blur(self):
        self.run_ui_scenario(r"""
path.value = 'C:\\invalid\\codex.exe';
path.handlers.input();
// Native pointer focus transfer fires blur before the button's click.
path.handlers.blur({relatedTarget: detect});
assert.equal(detect.disabled, false, 'blur must not disable the pending detection click');
const detection = detect.handlers.click();
assert.deepEqual(statusRequests, [{codex_path: ''}], 'detect must ignore the edited path');
resolveStatus({ok: true, json: async () => ({available: true, authenticated: true,
  path: 'C:\\desktop\\codex.exe', source: 'desktop', version: 'test-version', error: ''})});
await detection;
assert.equal(path.value, 'C:\\desktop\\codex.exe');
assert.match(element('codex-runtime-status').textContent, /test-version/);
assert.deepEqual(JSON.parse(saved.get('modeltrace.codex-test.preferences')),
  {manualPath: '', model: 'gpt-6-astra', reasoningEffort: 'low', useUserConfig: false});
assert.equal(detect.disabled, false);
""")

    def test_api_submission_starts_while_codex_status_is_pending(self):
        self.run_ui_scenario(r"""
const detection = detect.handlers.click();
assert.equal(element('api-submit').disabled, false);
await element('api-test-form').handlers.submit({preventDefault() {}});
assert.equal(challengeRequests, 3, 'API must load its two batches during Codex status');
assert.equal(element('api-test-progress').hidden, false);
resolveStatus({ok: true, json: async () => ({available: true, authenticated: true,
  path: 'C:\\desktop\\codex.exe', source: 'desktop', version: 'test-version', error: ''})});
await detection;
""")

    def test_auto_detect_clears_manual_override_even_when_discovery_fails(self):
        failed_statuses = (
            {"available": False, "authenticated": False, "path": "", "source": "",
             "version": "", "error": "No Codex found"},
            {"available": True, "authenticated": False, "path": r"C:\desktop\codex.exe",
             "source": "desktop", "version": "test-version", "error": "Please log in"},
        )
        for failed_status in failed_statuses:
            with self.subTest(available=failed_status["available"]):
                self.run_ui_scenario("const failedStatus = " + json.dumps(failed_status) + ";\n" + r"""
path.value = 'C:\\manual\\codex.exe';
path.handlers.input();
path.handlers.blur({relatedTarget: element('codex-model')});
resolveStatus({ok: true, json: async () => ({available: true, authenticated: true,
  path: 'C:\\manual\\codex.exe', source: 'manual', version: 'test-version', error: ''})});
await new Promise(resolve => setImmediate(resolve));
assert.equal(JSON.parse(saved.get('modeltrace.codex-test.preferences')).manualPath,
  'C:\\manual\\codex.exe', 'fixture must first save a successful manual override');
const detection = detect.handlers.click();
assert.deepEqual(JSON.parse(saved.get('modeltrace.codex-test.preferences')),
  {manualPath: '', model: 'gpt-6-astra', reasoningEffort: 'low', useUserConfig: false},
  'choosing automatic detection must clear the saved manual path before the response');
assert.deepEqual(statusRequests.at(-1), {codex_path: ''});
resolveStatus({ok: true, json: async () => failedStatus});
await detection;
assert.equal(element('codex-runtime-status').className, 'message error');
assert.equal(JSON.parse(saved.get('modeltrace.codex-test.preferences')).manualPath, '');
// Even if the old visible path remains after failure, the next preflight must use auto mode.
const submission = element('codex-test-form').handlers.submit({preventDefault() {}});
assert.deepEqual(statusRequests.at(-1), {codex_path: ''},
  'failed automatic discovery must not restore the in-memory manual source');
resolveStatus({ok: true, json: async () => failedStatus});
await submission;
assert.equal(challengeRequests, 1, 'failed preflight must not launch a model probe');
""")

    def test_codex_user_config_preference_is_restored_submitted_and_preserved(self):
        self.run_ui_scenario(r"""
saved.set('modeltrace.codex-test.preferences', JSON.stringify({
  manualPath: '', model: 'gpt-6-astra', reasoningEffort: 'low', useUserConfig: true,
}));
const probePayloads = [];
const challenges = Array.from({length: 3}, (_, index) => ({
  prompt: `prompt-${index + 1}`, expected_count: 100 + index,
}));
globalThis.fetch = async (url, options) => {
  if (url === '/api/codex/status') {
    return {ok: true, json: async () => ({available: true, authenticated: true,
      path: 'C:\\desktop\\codex.exe', source: 'desktop', version: 'test-version', error: ''})};
  }
  if (url === '/api/codex/models') {
    return {ok: true, json: async () => ({models: [
      {id: 'deepseek-flash', label: 'DeepSeek Flash'},
    ]})};
  }
  if (url === '/api/challenges') {
    return {ok: true, json: async () => ({challenges})};
  }
  if (url === '/api/test/codex/probe') {
    probePayloads.push(JSON.parse(options.body));
    return {ok: true, json: async () => ({accepted: true, text: 'valid',
      parsed_numbers: 80, minimum_numbers: 80})};
  }
  if (url === '/api/analyze') {
    return {ok: true, json: async () => ({
      diagnostics: [], results: [{display_name: 'Model', family_name: 'Family',
        probability: 1, profile_similarity: 1}], prediction_name: 'Model',
      probability: 1, family_prediction_name: 'Family', family_probability: 1,
      used_outputs: 3,
    })};
  }
  throw new Error(`Unexpected URL: ${url}`);
};
codexTab.handlers.click();
assert.equal(element('codex-use-user-config').checked, true,
  'stored preference must restore the checkbox');
await new Promise(resolve => setImmediate(resolve));
await element('codex-test-form').handlers.submit({preventDefault() {}});
assert.equal(probePayloads.length, 3);
for (const payload of probePayloads) {
  assert.equal(payload.use_user_config, true,
    'the checked preference must be sent to every Codex probe');
}
assert.deepEqual(JSON.parse(saved.get('modeltrace.codex-test.preferences')), {
  manualPath: '', model: 'gpt-6-astra', reasoningEffort: 'low', useUserConfig: true,
});
""")

    def test_codex_model_catalog_loads_refreshes_and_keeps_free_input(self):
        self.run_ui_scenario(r"""
globalThis.fetch = async (url, options) => {
  if (url === '/api/codex/status') {
    return {ok: true, json: async () => ({available: true, authenticated: true,
      path: 'C:\\desktop\\codex.exe', source: 'desktop', version: 'test-version', error: ''})};
  }
  if (url === '/api/codex/models') {
    modelRequests.push(JSON.parse(options.body));
    const custom = JSON.parse(options.body).use_user_config;
    return {ok: true, json: async () => ({models: custom
      ? [{id: 'deepseek-flash', label: 'DeepSeek Flash'}]
      : [{id: 'gpt-6-astra', label: 'GPT-6 Astra'}]})};
  }
  if (url === '/api/challenges') {
    return {ok: true, json: async () => ({challenges: []})};
  }
  throw new Error(`Unexpected URL: ${url}`);
};
codexTab.handlers.click();
await new Promise(resolve => setImmediate(resolve));
assert.deepEqual(modelRequests, [{codex_path: 'C:\\desktop\\codex.exe', use_user_config: false}]);
assert.match(element('codex-model-menu').innerHTML, /data-model-id="gpt-6-astra"/);

const model = element('codex-model');
model.value = 'vendor/manual-model';
const toggle = element('codex-use-user-config');
toggle.checked = true;
await toggle.handlers.change();
assert.equal(model.value, 'vendor/manual-model', 'catalog refresh must preserve arbitrary input');
assert.deepEqual(modelRequests.at(-1), {
  codex_path: 'C:\\desktop\\codex.exe', use_user_config: true,
});
const menu = element('codex-model-menu');
assert.match(menu.innerHTML, /data-model-id="deepseek-flash"/);

model.value = 'gpt';
if (model.handlers.input) model.handlers.input({target: model});
await element('codex-model-toggle').handlers.click();
assert.equal(menu.hidden, false);
assert.match(menu.innerHTML, /data-model-id="deepseek-flash"/,
  'typing must not filter the complete model list');
menu.handlers.click({target: {closest: () => ({dataset: {modelId: 'deepseek-flash'}})}});
assert.equal(model.value, 'deepseek-flash');
assert.equal(menu.hidden, true);

model.value = 'vendor/manual-model';
await element('codex-model-refresh').handlers.click();
assert.equal(modelRequests.length, 3, 'the in-field refresh button must reload the catalog');
assert.equal(model.value, 'vendor/manual-model');
""")

    def test_mixed_automatic_failures_keep_escaped_attempt_summaries(self):
        replies = [
            {"ok": True, "payload": {"accepted": False, "text": "short", "parsed_numbers": 12, "minimum_numbers": 80}},
            {"ok": False, "payload": {"error": "<img src=x onerror=alert(1)>"}},
            {"ok": True, "payload": {"accepted": True, "text": "valid", "parsed_numbers": 80, "minimum_numbers": 80}},
            {"ok": False, "payload": {"error": "timeout"}},
            {"ok": False, "payload": {"error": "model unavailable"}},
            {"ok": False, "payload": {"error": "retry exhausted"}},
        ]
        self.run_automatic_ui_scenario(replies, r"""
await element('api-test-form').handlers.submit({preventDefault() {}});
assert.equal(analyzed, true);
const progress = element('api-progress-steps').innerHTML;
assert.match(progress, /挑战 1 · 数字不足 · 有效数字 12\/80/);
assert.match(progress, /挑战 2 · 请求失败 · &lt;img src=x onerror=alert\(1\)&gt;/);
assert.doesNotMatch(progress, /<img src=x/);
const result = element('result').innerHTML;
assert.match(result, /挑战 1：有效数字 12\/80/);
assert.match(result, /挑战 2：&lt;img src=x onerror=alert\(1\)&gt;/);
assert.doesNotMatch(result, /<img src=x/);
""")

    def test_all_failed_automatic_run_keeps_every_attempt_summary(self):
        replies = [
            {"ok": False, "payload": {"error": f"failure-{index}"}}
            for index in range(1, 7)
        ]
        self.run_automatic_ui_scenario(replies, r"""
await element('api-test-form').handlers.submit({preventDefault() {}});
assert.equal(analyzed, false);
const progress = element('api-progress-steps').innerHTML;
for (let attempt = 1; attempt <= 6; attempt += 1) {
  assert.match(progress, new RegExp(`挑战 ${attempt} · 请求失败 · failure-${attempt}`));
}
assert.match(element('test-message').textContent, /6 次未采用/);
assert.match(element('test-message').textContent, /挑战 6：failure-6/);
""")

    def test_candy_api_batch_uses_frozen_question_and_renders_answers_safely(self):
        self.run_candy_ui_scenario(r"""
assert.equal(element('candy-question-prompt').textContent, question.prompt);
element('candy-api-base').value = 'https://example.test/v1';
element('candy-api-key').value = 'private-key';
element('candy-api-model').value = 'model-a';
element('candy-api-format').value = 'openai';
element('candy-api-temperature').value = '';
element('candy-api-rounds').value = '2';
element('candy-api-timeout').value = '600';
await element('candy-api-form').handlers.submit({preventDefault() {}});
assert.equal(probePayloads.length, 2);
for (const payload of probePayloads) {
  assert.equal(payload.question_id, 'candy-v1');
  assert.equal(payload.timeout_seconds, 600);
  assert.equal(payload.api_format, 'openai');
  assert.equal(payload.api_key, 'private-key');
}
assert.equal(element('candy-batch-question').textContent, question.prompt);
assert.match(element('candy-summary').textContent, /已完成 2\/2/);
assert.match(element('candy-summary').textContent, /计划轮数 2/);
assert.match(element('candy-summary').textContent, /未执行 0/);
assert.match(element('candy-summary').textContent, /可判定 1/);
const rows = element('candy-result-rows').innerHTML;
assert.match(rows, /&lt;img src=x onerror=alert\(1\)&gt;/);
assert.doesNotMatch(rows, /<img src=x/);
assert.match(rows, /待判定/);
assert.match(rows, /缺少最终答案标签/);
assert.match(rows, /2\.064 秒/);
assert.doesNotMatch(rows, /2\.0636650000233203/);
libraryNav.handlers.click();
candyNav.handlers.click();
candyApiTab.handlers.click();
assert.equal(element('candy-result-rows').innerHTML, rows, 'navigation and tab switching must preserve current results');
const persisted = [...saved.values()].join('\n');
for (const secret of ['private-key', '<img src=x', '没有标签', '<final-answer>21</final-answer>']) {
  assert.doesNotMatch(persisted, new RegExp(secret.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')),
    'API keys, answers, and results must not be persisted');
}
""")

    def test_invalid_candy_api_preflight_preserves_previous_batch(self):
        self.run_candy_ui_scenario(r"""
element('candy-api-base').value = 'https://example.test/v1';
element('candy-api-key').value = 'private-key';
element('candy-api-model').value = 'model-a';
element('candy-api-format').value = 'openai';
element('candy-api-temperature').value = '';
element('candy-api-rounds').value = '1';
element('candy-api-timeout').value = '600';
await element('candy-api-form').handlers.submit({preventDefault() {}});
const previousSummary = element('candy-summary').textContent;
const previousRows = element('candy-result-rows').innerHTML;
element('candy-api-base').value = 'not-a-url';
await element('candy-api-form').handlers.submit({preventDefault() {}});
assert.equal(probePayloads.length, 1, 'invalid configuration must not start another round');
assert.equal(element('candy-summary').textContent, previousSummary);
assert.equal(element('candy-result-rows').innerHTML, previousRows);
assert.match(element('candy-message').textContent, /Base URL/);
""")

    def test_candy_codex_submission_uses_selected_model_and_user_config(self):
        self.run_candy_ui_scenario(r"""
const baseFetch = globalThis.fetch;
let statusCalls = 0;
const codexPayloads = [];
globalThis.fetch = async (url, options) => {
  if (url === '/api/codex/status') {
    statusCalls += 1;
    return {ok: true, status: 200, json: async () => ({available: true, authenticated: true,
      path: 'C:\\desktop\\codex.exe', source: 'desktop', version: 'test-version', error: ''})};
  }
  if (url === '/api/codex/models') return {ok: true, status: 200, json: async () => ({models: [
    {id: 'deepseek-flash', label: 'DeepSeek Flash'},
  ]})};
  if (url === '/api/candy/codex/probe') {
    codexPayloads.push(JSON.parse(options.body));
    return {ok: true, status: 200, json: async () => ({question_id: 'candy-v1', status: 'correct',
      answer: 'Codex answer <final-answer>21</final-answer>', final_answer: 21,
      grading_reason: '答案正确', usage: null, elapsed_seconds: 1, tps: null, error: null})};
  }
  return baseFetch(url, options);
};
candyCodexTab.handlers.click();
await new Promise(resolve => setImmediate(resolve));
element('candy-codex-model').value = 'deepseek-flash';
element('candy-codex-reasoning-effort').value = 'high';
element('candy-codex-use-user-config').checked = true;
element('candy-codex-rounds').value = '1';
element('candy-codex-timeout').value = '600';
await element('candy-codex-form').handlers.submit({preventDefault() {}});
assert.equal(codexPayloads.length, 1);
assert.equal(codexPayloads[0].model, 'deepseek-flash');
assert.equal(codexPayloads[0].use_user_config, true);
assert.equal(codexPayloads[0].reasoning_effort, 'high');
assert.equal(codexPayloads[0].codex_path, 'C:\\desktop\\codex.exe');
const previousRows = element('candy-result-rows').innerHTML;
const previousStatusCalls = statusCalls;
element('candy-codex-model').value = 'bad model';
await element('candy-codex-form').handlers.submit({preventDefault() {}});
assert.equal(statusCalls, previousStatusCalls, 'an invalid model must be rejected before Codex preflight');
assert.equal(codexPayloads.length, 1);
assert.equal(element('candy-result-rows').innerHTML, previousRows);
assert.match(element('candy-message').textContent, /模型/);
const persisted = [...saved.values()].join('\n');
assert.doesNotMatch(persisted, /Codex answer|final-answer|调用失败/);
""")

    def test_candy_codex_preflight_holds_global_test_mutex(self):
        self.run_candy_ui_scenario(r"""
element('candy-codex-model').value = 'deepseek-flash';
element('candy-codex-reasoning-effort').value = 'high';
element('candy-codex-use-user-config').checked = true;
element('candy-codex-rounds').value = '1';
element('candy-codex-timeout').value = '600';
element('candy-api-base').value = 'https://example.test/v1';
element('candy-api-key').value = 'private-key';
element('candy-api-model').value = 'model-a';
element('candy-api-format').value = 'openai';
element('candy-api-rounds').value = '1';
element('candy-api-timeout').value = '600';
let resolveStatus;
let candyApiProbes = 0;
let challengeLoads = 0;
globalThis.fetch = async (url) => {
  if (url === '/api/codex/status') return new Promise(resolve => { resolveStatus = resolve; });
  if (url === '/api/candy/api/probe') { candyApiProbes += 1; throw new Error('must not run'); }
  if (url === '/api/challenges') { challengeLoads += 1; return {ok: true, status: 200, json: async () => ({challenges: []})}; }
  if (url === '/api/candy/question') return {ok: true, status: 200, json: async () => question};
  throw new Error(`Unexpected URL: ${url}`);
};
const codexRun = element('candy-codex-form').handlers.submit({preventDefault() {}});
await new Promise(resolve => setImmediate(resolve));
assert.equal(element('candy-api-start').disabled, true);
assert.equal(element('api-submit').disabled, true);
await element('candy-api-form').handlers.submit({preventDefault() {}});
await element('api-test-form').handlers.submit({preventDefault() {}});
assert.equal(candyApiProbes, 0, 'Candy API must not start during Codex preflight');
assert.equal(challengeLoads, 0, 'fingerprint automatic test must not start during Candy preflight');
resolveStatus({ok: true, status: 200, json: async () => ({available: false, authenticated: false,
  path: '', source: '', version: '', error: 'Codex unavailable'})});
await codexRun;
assert.equal(element('candy-api-start').disabled, false);
assert.equal(element('api-submit').disabled, false);
""")

    def test_candy_stop_waits_for_current_round_and_marks_remaining_rows(self):
        self.run_candy_ui_scenario(r"""
element('candy-api-base').value = 'https://example.test/v1';
element('candy-api-key').value = 'private-key';
element('candy-api-model').value = 'model-a';
element('candy-api-format').value = 'openai';
element('candy-api-rounds').value = '3';
element('candy-api-timeout').value = '600';
let resolveProbe;
let probes = 0;
globalThis.fetch = async (url) => {
  if (url === '/api/challenges') return {ok: true, status: 200, json: async () => ({challenges: []})};
  if (url === '/api/candy/question') return {ok: true, status: 200, json: async () => question};
  if (url === '/api/candy/api/probe') {
    probes += 1;
    return new Promise(resolve => { resolveProbe = resolve; });
  }
  throw new Error(`Unexpected URL: ${url}`);
};
const running = element('candy-api-form').handlers.submit({preventDefault() {}});
await new Promise(resolve => setImmediate(resolve));
assert.match(element('candy-result-rows').innerHTML, /执行中/);
assert.equal((element('candy-result-rows').innerHTML.match(/等待中/g) || []).length, 2);
element('candy-stop').handlers.click();
assert.match(element('candy-progress-status').textContent, /当前轮结束后停止/);
resolveProbe({ok: true, status: 200, json: async () => ({question_id: 'candy-v1', status: 'correct',
  answer: '<final-answer>21</final-answer>', final_answer: 21, grading_reason: '答案正确',
  usage: null, elapsed_seconds: 1, tps: null, error: null})});
await running;
assert.equal(probes, 1);
assert.equal((element('candy-result-rows').innerHTML.match(/未执行/g) || []).length, 2);
assert.match(element('candy-summary').textContent, /已完成 1\/3/);
assert.match(element('candy-summary').textContent, /未执行 2/);
""")

    def test_candy_refreshes_question_and_stops_after_version_or_parameter_error(self):
        self.run_candy_ui_scenario(r"""
element('candy-api-base').value = 'https://example.test/v1';
element('candy-api-key').value = 'private-key';
element('candy-api-model').value = 'model-a';
element('candy-api-format').value = 'openai';
element('candy-api-rounds').value = '1';
element('candy-api-timeout').value = '600';
let questionGets = 0;
let nextQuestionVersion = 2;
const seenQuestionIds = [];
let failNextQuestion = false;
globalThis.fetch = async (url, options) => {
  if (url === '/api/challenges') return {ok: true, status: 200, json: async () => ({challenges: []})};
  if (url === '/api/candy/question') {
    questionGets += 1;
    if (failNextQuestion) {
      failNextQuestion = false;
      return {ok: false, status: 503, json: async () => ({error: 'question unavailable'})};
    }
    const version = nextQuestionVersion;
    nextQuestionVersion += 1;
    return {ok: true, status: 200, json: async () => ({
      question_id: `candy-v${version}`, title: '糖果题', prompt: `prompt-${version}`,
    })};
  }
  if (url === '/api/candy/api/probe') {
    const payload = JSON.parse(options.body);
    seenQuestionIds.push(payload.question_id);
    if (payload.question_id === 'candy-v3') {
      return {ok: false, status: 409, json: async () => ({error: '题目版本已变更'})};
    }
    if (payload.question_id === 'candy-v5') {
      return {ok: false, status: 400, json: async () => ({error: '参数无效'})};
    }
    return {ok: true, status: 200, json: async () => ({question_id: payload.question_id,
      status: 'correct', answer: '<final-answer>21</final-answer>', final_answer: 21,
      grading_reason: '答案正确', usage: null, elapsed_seconds: 1, tps: null, error: null})};
  }
  throw new Error(`Unexpected URL: ${url}`);
};
await element('candy-api-form').handlers.submit({preventDefault() {}});
assert.deepEqual(seenQuestionIds, ['candy-v2']);
const previousRows = element('candy-result-rows').innerHTML;
failNextQuestion = true;
await element('candy-api-form').handlers.submit({preventDefault() {}});
assert.equal(element('candy-result-rows').innerHTML, previousRows, 'question fetch failure preserves old batch');
element('candy-api-rounds').value = '3';
await element('candy-api-form').handlers.submit({preventDefault() {}});
assert.deepEqual(seenQuestionIds, ['candy-v2', 'candy-v3']);
assert.equal((element('candy-result-rows').innerHTML.match(/未执行/g) || []).length, 2);
element('candy-api-rounds').value = '1';
await element('candy-api-form').handlers.submit({preventDefault() {}});
assert.deepEqual(seenQuestionIds, ['candy-v2', 'candy-v3', 'candy-v4'],
  'the run after a 409 must fetch and use a fresh question');
element('candy-api-rounds').value = '3';
await element('candy-api-form').handlers.submit({preventDefault() {}});
assert.deepEqual(seenQuestionIds, ['candy-v2', 'candy-v3', 'candy-v4', 'candy-v5'],
  'an HTTP 400 must consume only the current round');
assert.equal((element('candy-result-rows').innerHTML.match(/未执行/g) || []).length, 2);
""")


if __name__ == "__main__":
    unittest.main()
