from pathlib import Path
import json
import subprocess
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

    def run_ui_scenario(self, scenario):
        # Execute the real UI module. Only the DOM and HTTP boundaries are doubles;
        # keep the production listeners, busy state, path fill, and persistence real.
        script = r"""
import assert from 'node:assert/strict';
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    id, value: '', _disabled: false, style: {}, dataset: {}, handlers: {},
    get disabled() { return this._disabled; },
    set disabled(value) { this._disabled = Boolean(value); },
    classList: { toggle() {} },
    addEventListener(type, handler) { this.handlers[type] = handler; },
    closest(selector) {
      if (selector === '#codex-test-form button') {
        return id === 'codex-detect' || id === 'codex-submit' ? this : null;
      }
      return id.startsWith('codex-') ? element('codex-test-form') : null;
    },
  });
  return elements.get(id);
}
const controls = ['codex-path', 'codex-model', 'codex-reasoning-effort',
  'codex-detect', 'codex-submit', 'api-submit'].map(element);
const saved = new Map();
globalThis.window = {
  DEFAULT_BANK_ID: 'bank', BANK_SUMMARIES: {bank: {label: 'Test', models: []}},
  localStorage: {getItem: key => saved.get(key) ?? null,
    setItem: (key, value) => saved.set(key, value)},
};
globalThis.document = {
  getElementById: element,
  querySelectorAll: selector => selector.startsWith('#api-test-form') ? controls : [],
};
const statusRequests = [];
let challengeRequests = 0;
let resolveStatus;
globalThis.fetch = async (url, options) => {
  if (url === '/api/challenges') {
    challengeRequests += 1;
    return {ok: true, json: async () => ({challenges: []})};
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
            timeout=15,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def run_automatic_ui_scenario(self, replies, scenario):
        script = r"""
import assert from 'node:assert/strict';
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    id, value: '', hidden: true, textContent: '', innerHTML: '', className: '',
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
const controls = ['codex-path', 'codex-model', 'codex-reasoning-effort',
  'codex-detect', 'codex-submit', 'api-submit'].map(element);
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
  {manualPath: '', model: 'gpt-6-astra', reasoningEffort: 'low'});
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
  {manualPath: '', model: 'gpt-6-astra', reasoningEffort: 'low'},
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


if __name__ == "__main__":
    unittest.main()
