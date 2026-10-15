"""HTTP boundaries for Codex runtime status and automatic test probes."""

from flask import Blueprint, jsonify, request

from automatic_testing import evaluate_probe
from codex_runner import (
    CodexAuthenticationError,
    CodexExecutionError,
    CodexUnavailableError,
    get_codex_status,
    request_codex_completion,
)


codex_blueprint = Blueprint("codex", __name__)


def _codex_path(payload):
    path = payload.get("codex_path", "")
    if not isinstance(path, str):
        raise ValueError("codex_path 必须是字符串")
    return path.strip()


@codex_blueprint.post("/api/codex/status")
def codex_status():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    try:
        if not isinstance(payload, dict):
            raise ValueError("请求内容必须是 JSON 对象")
        return jsonify(get_codex_status(_codex_path(payload)))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@codex_blueprint.post("/api/test/codex/probe")
def codex_probe():
    payload = request.get_json(silent=True)
    try:
        if not isinstance(payload, dict):
            raise ValueError("请求内容必须是 JSON 对象")
        codex_path = _codex_path(payload)
        model = payload.get("model")
        prompt = payload.get("prompt")
        expected_count = payload.get("expected_count")
        reasoning_effort = payload.get("reasoning_effort")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model 必须是非空字符串")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt 必须是非空字符串")
        if type(expected_count) is not int or expected_count <= 0:
            raise ValueError("expected_count 必须是正整数")
        if reasoning_effort not in ("low", "medium", "high", "xhigh"):
            raise ValueError("reasoning_effort 仅支持 low、medium、high、xhigh")
        text = request_codex_completion(codex_path, model, reasoning_effort, prompt)
        return jsonify(evaluate_probe(text, expected_count))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except (CodexUnavailableError, CodexAuthenticationError) as error:
        return jsonify({"error": str(error)}), 503
    except CodexExecutionError as error:
        return jsonify({"error": str(error)}), 502
