import unittest
from unittest.mock import patch

from flask import Flask

from codex_routes import codex_blueprint
from codex_runner import (
    CodexAuthenticationError,
    CodexExecutionError,
    CodexUnavailableError,
)


ANSWER = (
    "1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,"
    "21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,"
    "41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59,60,"
    "61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80"
)
STATUS = {
    "available": True,
    "authenticated": True,
    "path": "C:/Codex/codex.exe",
    "source": "manual",
    "version": "0.162.0-alpha.17.2",
}


class CodexRouteTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(codex_blueprint)
        self.client = app.test_client()
        self.payload = {
            "codex_path": "  C:/Codex/codex.exe  ",
            "model": "gpt-5.4",
            "reasoning_effort": "high",
            "prompt": "Return 100 integers.",
            "expected_count": 100,
        }

    def test_status_returns_resolved_runtime_details(self):
        with patch("codex_routes.get_codex_status", return_value=STATUS) as status:
            response = self.client.post("/api/codex/status", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), STATUS)
        status.assert_called_once_with("")

    def test_status_returns_unavailable_details_without_hiding_error(self):
        unavailable = {
            "available": False, "authenticated": False,
            "path": "", "source": "", "version": "", "error": "未找到 codex.exe",
        }
        with patch("codex_routes.get_codex_status", return_value=unavailable):
            response = self.client.post("/api/codex/status", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), unavailable)

    def test_status_accepts_absent_body_and_normalizes_path(self):
        with patch("codex_routes.get_codex_status", return_value=STATUS) as status:
            response = self.client.post("/api/codex/status")
            self.assertEqual(response.status_code, 200)
            status.assert_called_once_with("")
        with patch("codex_routes.get_codex_status", return_value=STATUS) as status:
            response = self.client.post("/api/codex/status", json={"codex_path": "  C:/Codex/codex.exe  "})
            self.assertEqual(response.status_code, 200)
            status.assert_called_once_with("C:/Codex/codex.exe")

    def test_status_preserves_unauthenticated_details(self):
        unauthenticated = {**STATUS, "authenticated": False, "error": "Codex 未登录"}
        with patch("codex_routes.get_codex_status", return_value=unauthenticated):
            response = self.client.post("/api/codex/status", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), unauthenticated)

    def test_probe_returns_shared_acceptance_contract(self):
        with patch("codex_routes.request_codex_completion", return_value=ANSWER) as completion:
            response = self.client.post("/api/test/codex/probe", json=self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "text": ANSWER, "parsed_numbers": 80, "minimum_numbers": 80, "accepted": True,
        })
        completion.assert_called_once_with(
            "C:/Codex/codex.exe", "gpt-5.4", "high", "Return 100 integers.",
            use_user_config=False,
        )

    def test_probe_forwards_explicit_user_config_mode(self):
        for use_user_config in (False, True):
            with self.subTest(use_user_config=use_user_config):
                payload = {**self.payload, "use_user_config": use_user_config}
                with patch(
                    "codex_routes.request_codex_completion", return_value=ANSWER
                ) as completion:
                    response = self.client.post("/api/test/codex/probe", json=payload)
                self.assertEqual(response.status_code, 200)
                completion.assert_called_once_with(
                    "C:/Codex/codex.exe", "gpt-5.4", "high",
                    "Return 100 integers.", use_user_config=use_user_config,
                )

    def assert_invalid_payload(self, payload):
        with patch(
            "codex_routes.request_codex_completion", return_value=ANSWER
        ) as completion:
            response = self.client.post("/api/test/codex/probe", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.get_json()["error"])
        completion.assert_not_called()

    def test_probe_rejects_missing_model_with_400(self):
        payload = dict(self.payload)
        del payload["model"]
        self.assert_invalid_payload(payload)

    def test_probe_rejects_unknown_reasoning_effort_with_400(self):
        self.assert_invalid_payload({**self.payload, "reasoning_effort": "ultra"})

    def test_probe_rejects_invalid_input_before_runtime(self):
        for field, values in {
            "model": [None, "", "  ", 5],
            "prompt": [None, "", "  ", 5],
            "expected_count": [None, 0, -1, True, 1.5, "100"],
            "reasoning_effort": [None, "", 5],
            "codex_path": [5, []],
            "use_user_config": [None, "true", "false", 0, 1, [], {}],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assert_invalid_payload({**self.payload, field: value})
        for payload in [[], "payload", 42]:
            with self.subTest(payload=payload):
                self.assert_invalid_payload(payload)
        with patch("codex_routes.request_codex_completion") as completion:
            response = self.client.post("/api/test/codex/probe")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.get_json()["error"])
        completion.assert_not_called()

    def test_probe_accepts_all_four_efforts_and_optional_path(self):
        for effort in ["low", "medium", "high", "xhigh"]:
            with self.subTest(effort=effort):
                payload = {**self.payload, "reasoning_effort": effort}
                del payload["codex_path"]
                with patch("codex_routes.request_codex_completion", return_value=ANSWER) as completion:
                    response = self.client.post("/api/test/codex/probe", json=payload)
                self.assertEqual(response.status_code, 200)
                completion.assert_called_once_with(
                    "", "gpt-5.4", effort, "Return 100 integers.",
                    use_user_config=False,
                )

    def test_probe_maps_unavailable_and_authentication_errors_to_503(self):
        for error in [CodexUnavailableError("未找到 codex.exe"), CodexAuthenticationError("Codex 未登录")]:
            with self.subTest(error=error):
                with patch("codex_routes.request_codex_completion", side_effect=error):
                    response = self.client.post("/api/test/codex/probe", json=self.payload)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.get_json(), {"error": str(error)})

    def test_probe_maps_execution_error_to_502(self):
        with patch("codex_routes.request_codex_completion", side_effect=CodexExecutionError("Codex CLI 执行失败")):
            response = self.client.post("/api/test/codex/probe", json=self.payload)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json(), {"error": "Codex CLI 执行失败"})

    def test_probe_maps_timeout_error_to_502(self):
        with patch("codex_routes.request_codex_completion", side_effect=CodexExecutionError("Codex 执行超过 120 秒，已终止")):
            response = self.client.post("/api/test/codex/probe", json=self.payload)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json(), {"error": "Codex 执行超过 120 秒，已终止"})

    def test_probe_maps_runtime_validation_error_to_400(self):
        with patch("codex_routes.request_codex_completion", side_effect=ValueError("无效模型")):
            response = self.client.post("/api/test/codex/probe", json=self.payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "无效模型"})


class CodexApplicationRegistrationTests(unittest.TestCase):
    def test_application_registers_codex_status_endpoint(self):
        from app import app

        with patch("codex_routes.get_codex_status", return_value=STATUS):
            response = app.test_client().post("/api/codex/status", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["path"], "C:/Codex/codex.exe")
