"""Validate and time single-round candy evaluations for API and Codex."""

import math
import re
import time
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request

from candy_testing import DEFAULT_TIMEOUT_SECONDS, build_candy_result, question_payload
from completion_errors import StructuredCompletionError
from codex_runner import request_codex_completion_result
from enrollment import request_completion_result


candy_blueprint = Blueprint("candy", __name__)


def _required_string(payload, field):
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串")
    return value.strip()


def _probe_payload():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValueError("请求内容必须是 JSON 对象")
    question_id = _required_string(payload, "question_id")
    timeout = payload.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if type(timeout) is not int or not 30 <= timeout <= 1800:
        raise ValueError("timeout_seconds 必须是 30 到 1800 之间的整数")
    return payload, question_id, timeout


def _redact_credentials(text, api_key=""):
    if api_key:
        text = text.replace(api_key, "[已隐藏]")
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [已隐藏]", text)
    text = re.sub(
        r'''(?i)(["']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|authorization)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)''',
        r"\1[已隐藏]", text,
    )
    text = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[已隐藏]", text)
    return text


def _sanitized_error(error, api_key=""):
    text = _redact_credentials(str(error), api_key)
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    return " ".join(text.split())


def _timed_probe(completion, api_key=""):
    started = time.perf_counter()
    try:
        result = completion()
    except StructuredCompletionError as error:
        details = error.details
        answer = (
            _redact_credentials(details.text, api_key)
            if details.text is not None else None
        )
        return jsonify({
            "question_id": question_payload()["question_id"],
            "status": "error", "answer": answer, "final_answer": None,
            "grading_reason": None, "usage": details.usage,
            "elapsed_seconds": time.perf_counter() - started,
            "tps": None, "error": _sanitized_error(error, api_key),
        })
    except Exception as error:
        return jsonify({
            "question_id": question_payload()["question_id"],
            "status": "error", "answer": None, "final_answer": None,
            "grading_reason": None, "usage": None,
            "elapsed_seconds": time.perf_counter() - started,
            "tps": None, "error": _sanitized_error(error, api_key),
        })
    elapsed = time.perf_counter() - started
    candy_result = build_candy_result(result["text"], result["usage"], elapsed)
    candy_result["answer"] = _redact_credentials(result["text"], api_key)
    return jsonify(candy_result)


@candy_blueprint.get("/api/candy/question")
def candy_question():
    return jsonify(question_payload())


@candy_blueprint.post("/api/candy/api/probe")
def candy_api_probe():
    try:
        payload, question_id, timeout = _probe_payload()
        base_url = _required_string(payload, "base_url")
        parsed_url = urlsplit(base_url)
        if (
            parsed_url.scheme not in ("http", "https") or not parsed_url.hostname
            or parsed_url.username is not None or parsed_url.password is not None
        ):
            raise ValueError("base_url 必须是有效的 HTTP 或 HTTPS 地址")
        # Accessing port validates both its numeric syntax and supported range.
        parsed_url.port
        _required_string(payload, "api_key")
        api_key = payload["api_key"]
        api_model = _required_string(payload, "api_model")
        api_format = payload.get("api_format")
        if api_format not in ("openai", "anthropic"):
            raise ValueError("api_format 必须是 openai 或 anthropic")
        temperature = payload.get("temperature")
        if temperature is None or temperature == "":
            temperature = None
        elif type(temperature) not in (int, float) or not math.isfinite(temperature):
            raise ValueError("temperature 必须是有限数值或留空")
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    question = question_payload()
    if question_id != question["question_id"]:
        return jsonify({"error": "题目版本已变更，请重新获取题目后开始测试"}), 409
    return _timed_probe(lambda: request_completion_result(
        base_url=base_url, api_key=api_key, api_model=api_model,
        prompt=question["prompt"], temperature=temperature, api_format=api_format,
        timeout=timeout, max_attempts=1,
    ), api_key=api_key)


@candy_blueprint.post("/api/candy/codex/probe")
def candy_codex_probe():
    try:
        payload, question_id, timeout = _probe_payload()
        codex_path = payload.get("codex_path", "")
        if not isinstance(codex_path, str):
            raise ValueError("codex_path 必须是字符串")
        codex_path = codex_path.strip()
        model = _required_string(payload, "model")
        if re.fullmatch(r"[A-Za-z0-9._/:-]{1,128}", model) is None:
            raise ValueError("model 必须是有效的模型标识，最多 128 个字符")
        reasoning_effort = payload.get("reasoning_effort")
        if reasoning_effort not in ("low", "medium", "high", "xhigh"):
            raise ValueError("reasoning_effort 仅支持 low、medium、high、xhigh")
        use_user_config = payload.get("use_user_config", False)
        if type(use_user_config) is not bool:
            raise ValueError("use_user_config 必须是布尔值")
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    question = question_payload()
    if question_id != question["question_id"]:
        return jsonify({"error": "题目版本已变更，请重新获取题目后开始测试"}), 409
    return _timed_probe(lambda: request_codex_completion_result(
        codex_path=codex_path, model=model, reasoning_effort=reasoning_effort,
        prompt=question["prompt"], timeout=timeout, use_user_config=use_user_config,
    ))
