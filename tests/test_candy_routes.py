import unittest
from unittest.mock import patch

from flask import Flask

from candy_routes import candy_blueprint
from completion_errors import CompletionFailureDetails, StructuredCompletionError


PROMPT = """不使用任何外部工具回答以下问题：

在一个黑色的袋子里放有三种口味的糖果，每种糖果有两种不同的形状（圆形和五角星形，不同的形状靠手感可以分辨）。现已知不同口味的糖和不同形状的数量统计如下表。参赛者需要在活动前决定摸出的糖果数目，那么，最少取出多少个糖果才能保证手中同时拥有不同形状的苹果味和桃子味的糖？（同时手中有圆形苹果味匹配五角星桃子味糖果，或者有圆形桃子味匹配五角星苹果味糖果都满足要求）

        苹果味  桃子味  西瓜味
圆形       7      9      8
五角星形   7      6      4

请给出解题过程，并在回答最后使用 <final-answer>整数</final-answer> 输出最终答案。该标签只能出现一次，标签内不要包含单位、解释或其他内容。
"""
QUESTION = {
    "question_id": "candy-v1", "title": "最少需要取出多少颗糖果？", "prompt": PROMPT,
}
USAGE = {"input_tokens": 100, "output_tokens": 20, "reasoning_tokens": None}
CORRECT = "解题过程。<final-answer>21</final-answer>"


class CandyRouteTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(candy_blueprint)
        self.client = app.test_client()
        self.api_payload = {
            "question_id": "candy-v1", "base_url": "  https://example.test/v1  ",
            "api_key": "fixture-private-key", "api_model": "  fixture-model  ",
            "api_format": "openai",
        }
        self.codex_payload = {
            "question_id": "candy-v1", "codex_path": "  C:/Codex/codex.exe  ",
            "model": "fixture-model", "reasoning_effort": "high",
        }

    def probe(self, mode, payload, text=CORRECT, usage=USAGE):
        target = "request_completion_result" if mode == "api" else "request_codex_completion_result"
        with patch(f"candy_routes.{target}", return_value={"text": text, "usage": usage}) as completion:
            with patch("candy_routes.time.perf_counter", side_effect=[10.0, 12.5]):
                response = self.client.post(f"/api/candy/{mode}/probe", json=payload)
        return response, completion

    def test_question_returns_exact_public_payload_without_answer(self):
        response = self.client.get("/api/candy/question")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), QUESTION)

    def test_api_and_codex_return_exact_correct_result(self):
        for mode, payload in (("api", self.api_payload), ("codex", self.codex_payload)):
            with self.subTest(mode=mode):
                response, completion = self.probe(mode, payload)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), {
                    "question_id": "candy-v1", "status": "correct", "answer": CORRECT,
                    "final_answer": 21, "grading_reason": "答案正确", "usage": USAGE,
                    "elapsed_seconds": 2.5, "tps": 8.0, "error": None,
                })
                self.assertEqual(completion.call_count, 1)
                self.assertNotIn(self.api_payload["api_key"], response.get_data(as_text=True))

    def test_incorrect_and_ungraded_results_preserve_complete_answer(self):
        for mode, payload in (("api", self.api_payload), ("codex", self.codex_payload)):
            for text, status, final_answer, reason in (
                ("正文有21。<final-answer>20</final-answer>", "incorrect", 20, "答案错误"),
                ("无法回答，正文21。", "ungraded", None, "缺少最终答案标签"),
            ):
                with self.subTest(mode=mode, status=status):
                    response, _ = self.probe(mode, payload, text=text, usage=None)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.get_json(), {
                        "question_id": "candy-v1", "status": status, "answer": text,
                        "final_answer": final_answer, "grading_reason": reason, "usage": None,
                        "elapsed_seconds": 2.5, "tps": None, "error": None,
                    })

    def test_api_forwards_explicit_protocol_fixed_prompt_and_single_attempt(self):
        for api_format in ("openai", "anthropic"):
            with self.subTest(api_format=api_format):
                response, completion = self.probe("api", {
                    **self.api_payload, "api_format": api_format, "temperature": 0,
                    "prompt": "User supplied replacement must not be sent",
                })
                self.assertEqual(response.status_code, 200)
                completion.assert_called_once_with(
                    base_url="https://example.test/v1", api_key="fixture-private-key",
                    api_model="fixture-model", prompt=PROMPT, temperature=0,
                    api_format=api_format, timeout=600, max_attempts=1,
                    reasoning_effort=None,
                )

    def test_codex_forwards_fixed_prompt_effort_and_user_configuration(self):
        for use_user_config in (False, True):
            for effort in ("low", "medium", "high", "xhigh"):
                with self.subTest(use_user_config=use_user_config, effort=effort):
                    response, completion = self.probe("codex", {
                        **self.codex_payload, "reasoning_effort": effort,
                        "use_user_config": use_user_config,
                    })
                    self.assertEqual(response.status_code, 200)
                    completion.assert_called_once_with(
                        codex_path="C:/Codex/codex.exe", model="fixture-model",
                        reasoning_effort=effort, prompt=PROMPT, timeout=600,
                        use_user_config=use_user_config,
                    )

    def test_codex_optional_path_and_user_config_default(self):
        payload = dict(self.codex_payload)
        del payload["codex_path"]
        response, completion = self.probe("codex", payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(completion.call_args.kwargs["codex_path"], "")
        self.assertIs(completion.call_args.kwargs["use_user_config"], False)

    def test_timeout_default_and_custom_inclusive_bounds_reach_transport(self):
        for mode, payload in (("api", self.api_payload), ("codex", self.codex_payload)):
            for timeout in (None, 30, 75, 1800):
                with self.subTest(mode=mode, timeout=timeout):
                    request_payload = dict(payload)
                    if timeout is not None:
                        request_payload["timeout_seconds"] = timeout
                    response, completion = self.probe(mode, request_payload)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(completion.call_args.kwargs["timeout"], timeout or 600)

    def test_optional_temperature_uses_upstream_default(self):
        for temperature in (None, ""):
            with self.subTest(temperature=temperature):
                response, completion = self.probe("api", {**self.api_payload, "temperature": temperature})
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(completion.call_args.kwargs["temperature"])

    def test_api_reasoning_effort_is_optional_and_openai_only(self):
        for api_format, supplied, expected in (
            ("openai", "high", "high"),
            ("openai", None, None),
            ("openai", "", None),
            ("anthropic", "high", None),
        ):
            with self.subTest(api_format=api_format, supplied=supplied):
                payload = {**self.api_payload, "api_format": api_format}
                if supplied is not None:
                    payload["reasoning_effort"] = supplied
                response, completion = self.probe("api", payload)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(completion.call_args.kwargs["reasoning_effort"], expected)

    def test_api_rejects_nonstandard_reasoning_effort_before_transport(self):
        for value in ("max", "ultra", "HIGH", 1, True, [], {}):
            with self.subTest(value=value):
                self.assert_rejected_before_transport(
                    "api", {**self.api_payload, "reasoning_effort": value},
                )

    def assert_rejected_before_transport(self, mode, payload, status=400):
        with patch("candy_routes.request_completion_result", return_value={"text": CORRECT, "usage": USAGE}) as api:
            with patch("candy_routes.request_codex_completion_result", return_value={"text": CORRECT, "usage": USAGE}) as codex:
                response = self.client.post(f"/api/candy/{mode}/probe", json=payload)
        self.assertEqual(response.status_code, status)
        self.assertTrue(response.get_json()["error"])
        api.assert_not_called()
        codex.assert_not_called()

    def test_question_version_mismatch_is_409_before_transport(self):
        for mode, payload in (("api", self.api_payload), ("codex", self.codex_payload)):
            with self.subTest(mode=mode):
                self.assert_rejected_before_transport(mode, {**payload, "question_id": "candy-v0"}, 409)

    def test_common_invalid_parameters_are_400_before_transport(self):
        for mode, payload in (("api", self.api_payload), ("codex", self.codex_payload)):
            for field, values in {
                "question_id": [None, "", "  ", False, 1, []],
                "timeout_seconds": [None, True, False, 29, 1801, 30.0, "600", [], {}],
            }.items():
                for value in values:
                    with self.subTest(mode=mode, field=field, value=value):
                        self.assert_rejected_before_transport(mode, {**payload, field: value})
            for bad_payload in ([], "payload", 42):
                with self.subTest(mode=mode, payload=bad_payload):
                    self.assert_rejected_before_transport(mode, bad_payload)
            missing_question = dict(payload)
            del missing_question["question_id"]
            self.assert_rejected_before_transport(mode, missing_question)

    def test_missing_and_malformed_json_are_400_before_transport(self):
        for mode in ("api", "codex"):
            for body in (None, "{"):
                with self.subTest(mode=mode, body=body):
                    with patch("candy_routes.request_completion_result") as api:
                        with patch("candy_routes.request_codex_completion_result") as codex:
                            response = self.client.post(
                                f"/api/candy/{mode}/probe", data=body, content_type="application/json",
                            )
                    self.assertEqual(response.status_code, 400)
                    api.assert_not_called()
                    codex.assert_not_called()

    def test_api_invalid_parameters_are_400_before_transport(self):
        for field, values in {
            "base_url": [None, "", "  ", 5, [], "file:///secret", "invalid-url"],
            "api_key": [None, "", "  ", 5, []],
            "api_model": [None, "", "  ", 5, []],
            "api_format": [None, "auto", "", "OPENAI", 5, []],
            "temperature": [True, False, "1", [], {}, float("nan"), float("inf")],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assert_rejected_before_transport("api", {**self.api_payload, field: value})
        for field in ("base_url", "api_key", "api_model", "api_format"):
            with self.subTest(missing=field):
                payload = dict(self.api_payload)
                del payload[field]
                self.assert_rejected_before_transport("api", payload)

    def test_codex_invalid_parameters_are_400_before_transport(self):
        for field, values in {
            "codex_path": [None, 5, [], {}],
            "model": [None, "", "  ", 5, [], "bad model", "x" * 129],
            "reasoning_effort": [None, "", "ultra", 5, []],
            "use_user_config": [None, "true", "false", 0, 1, [], {}],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assert_rejected_before_transport("codex", {**self.codex_payload, field: value})
        for field in ("model", "reasoning_effort"):
            with self.subTest(missing=field):
                payload = dict(self.codex_payload)
                del payload[field]
                self.assert_rejected_before_transport("codex", payload)

    def test_api_rejects_missing_host_credentials_and_invalid_ports_before_transport(self):
        for base_url in (
            "https://user:pass@", "https://:443/v1", "https://example.test:bad",
            "https://example.test:65536", "https://user:pass@example.test/v1",
            "https://user@example.test/v1", "https://:password@example.test/v1",
        ):
            with self.subTest(base_url=base_url):
                self.assert_rejected_before_transport("api", {**self.api_payload, "base_url": base_url})

    def test_successful_answers_redact_echoed_credentials_without_losing_formatting(self):
        text = (
            "第一行解题过程。\n\n"
            "  Authorization: Bearer bearer-secret;\n"
            'api_key="other-private-key"\n'
            "access_token=access-secret\n"
            "refresh_token=refresh-secret\n"
            "token=token-secret\n"
            "裸令牌 sk-secretvalue\n"
            "\t最后计算得到：\n<final-answer>21</final-answer>\n"
        )
        for mode, payload in (("api", self.api_payload), ("codex", self.codex_payload)):
            with self.subTest(mode=mode):
                answer = text
                if mode == "api":
                    answer = answer.replace("第一行", "fixture-private-key 第一行")
                response, _ = self.probe(mode, payload, text=answer)
                self.assertEqual(response.status_code, 200)
                result = response.get_json()
                self.assertEqual(result["status"], "correct")
                self.assertEqual(result["final_answer"], 21)
                redacted = result["answer"]
                self.assertEqual(redacted.count("\n"), answer.count("\n"))
                self.assertIn("第一行解题过程。\n\n  Authorization:", redacted)
                self.assertTrue(redacted.endswith("\t最后计算得到：\n<final-answer>21</final-answer>\n"))
                for secret in (
                    "fixture-private-key", "bearer-secret", "other-private-key",
                    "access-secret", "refresh-secret", "token-secret", "sk-secretvalue",
                ):
                    self.assertNotIn(secret, response.get_data(as_text=True))

    def test_api_grades_raw_answer_before_redacting_a_short_key_from_display_text(self):
        payload = {**self.api_payload, "api_key": "1"}
        answer = "推理里回显密钥 1。<final-answer>21</final-answer>"

        response, _ = self.probe("api", payload, text=answer)

        result = response.get_json()
        self.assertEqual(result["status"], "correct")
        self.assertEqual(result["final_answer"], 21)
        self.assertEqual(result["grading_reason"], "答案正确")
        self.assertNotIn("1", result["answer"])
        self.assertIn("[已隐藏]", result["answer"])

    def test_structured_transport_failures_preserve_redacted_partial_answer_and_usage(self):
        usage = {"input_tokens": 80, "output_tokens": 12, "reasoning_tokens": 5}
        for mode, payload, target in (
            ("api", self.api_payload, "request_completion_result"),
            ("codex", self.codex_payload, "request_codex_completion_result"),
        ):
            with self.subTest(mode=mode):
                known_api_key = " fixture-private-key" if mode == "api" else ""
                answer = (
                    "部分回答 api_key=answer-secret "
                    f"{known_api_key} <final-answer>21</final-answer>"
                )
                failure = StructuredCompletionError(
                    f"上游失败 token=error-secret{known_api_key}",
                    details=CompletionFailureDetails(text=answer, usage=usage),
                )
                with patch(f"candy_routes.{target}", side_effect=failure):
                    with patch("candy_routes.time.perf_counter", side_effect=[4.0, 6.5]):
                        response = self.client.post(f"/api/candy/{mode}/probe", json=payload)

                self.assertEqual(response.status_code, 200)
                result = response.get_json()
                self.assertEqual(result["status"], "error")
                self.assertIsNone(result["final_answer"])
                self.assertIsNone(result["grading_reason"])
                self.assertIsNone(result["tps"])
                self.assertEqual(result["usage"], usage)
                self.assertEqual(result["elapsed_seconds"], 2.5)
                self.assertIn("部分回答", result["answer"])
                self.assertIn("上游失败", result["error"])
                secrets = ["answer-secret", "error-secret"]
                if mode == "api":
                    secrets.append("fixture-private-key")
                for secret in secrets:
                    self.assertNotIn(secret, response.get_data(as_text=True))

    def test_structured_transport_failure_without_partial_data_keeps_null_fields(self):
        for mode, payload, target in (
            ("api", self.api_payload, "request_completion_result"),
            ("codex", self.codex_payload, "request_codex_completion_result"),
        ):
            with self.subTest(mode=mode):
                failure = StructuredCompletionError("上游失败")
                with patch(f"candy_routes.{target}", side_effect=failure):
                    with patch("candy_routes.time.perf_counter", side_effect=[4.0, 5.0]):
                        response = self.client.post(f"/api/candy/{mode}/probe", json=payload)
                self.assertEqual(response.get_json(), {
                    "question_id": "candy-v1", "status": "error", "answer": None,
                    "final_answer": None, "grading_reason": None, "usage": None,
                    "elapsed_seconds": 1.0, "tps": None, "error": "上游失败",
                })

    def test_model_exceptions_are_timed_structured_errors_with_http_200(self):
        for mode, payload, target in (
            ("api", self.api_payload, "request_completion_result"),
            ("codex", self.codex_payload, "request_codex_completion_result"),
        ):
            for error in (RuntimeError("上游连接失败"), ValueError("上游响应无效")):
                with self.subTest(mode=mode, error=error):
                    with patch(f"candy_routes.{target}", side_effect=error) as completion:
                        with patch("candy_routes.time.perf_counter", side_effect=[5.0, 8.25]):
                            response = self.client.post(f"/api/candy/{mode}/probe", json=payload)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.get_json(), {
                        "question_id": "candy-v1", "status": "error", "answer": None,
                        "final_answer": None, "grading_reason": None, "usage": None,
                        "elapsed_seconds": 3.25, "tps": None, "error": str(error),
                    })
                    self.assertEqual(completion.call_count, 1)

    def test_error_preserves_cause_but_redacts_api_key_and_authentication_tokens(self):
        secret_error = (
            "\x1b[31m上游拒绝 fixture-private-key; Authorization: Bearer bearer-secret; "
            'api_key="other-private-key" access_token=access-secret sk-secretvalue\x1b[0m'
        )
        for mode, payload, target in (
            ("api", self.api_payload, "request_completion_result"),
            ("codex", self.codex_payload, "request_codex_completion_result"),
        ):
            with self.subTest(mode=mode):
                with patch(f"candy_routes.{target}", side_effect=RuntimeError(secret_error)):
                    response = self.client.post(f"/api/candy/{mode}/probe", json=payload)
                self.assertEqual(response.status_code, 200)
                error = response.get_json()["error"]
                self.assertIn("上游拒绝", error)
                for secret in ("bearer-secret", "other-private-key", "access-secret", "sk-secretvalue", "\x1b"):
                    self.assertNotIn(secret, error)
                if mode == "api":
                    self.assertNotIn("fixture-private-key", response.get_data(as_text=True))


class CandyApplicationRegistrationTests(unittest.TestCase):
    def test_application_registers_candy_blueprint(self):
        from app import app

        response = app.test_client().get("/api/candy/question")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), QUESTION)
