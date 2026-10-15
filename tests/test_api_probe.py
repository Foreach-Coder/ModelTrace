import io
import json
import unittest
import urllib.error
from unittest.mock import patch

import enrollment
from app import app


def openai_response():
    return {
        "id": "chatcmpl-fixture",
        "object": "chat.completion",
        "created": 1720000000,
        "model": "fixture-model",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "答案", "refusal": None},
            "logprobs": None,
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 40,
            "total_tokens": 140,
            "prompt_tokens_details": {"cached_tokens": 20, "audio_tokens": 0},
            "completion_tokens_details": {
                "reasoning_tokens": 25,
                "audio_tokens": 0,
                "accepted_prediction_tokens": 0,
                "rejected_prediction_tokens": 0,
            },
        },
        "system_fingerprint": None,
        "service_tier": "default",
    }


def anthropic_response():
    return {
        "id": "msg_fixture",
        "type": "message",
        "role": "assistant",
        "model": "fixture-model",
        "content": [
            {"type": "thinking", "thinking": "推理", "signature": "fixture-signature"},
            {"type": "text", "text": "答"},
            {"type": "text", "text": "案"},
        ],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 100,
            "cache_creation_input_tokens": 30,
            "cache_read_input_tokens": 20,
            "output_tokens": 40,
            "cache_creation": {"ephemeral_5m_input_tokens": 30, "ephemeral_1h_input_tokens": 0},
            "service_tier": "standard",
        },
    }


def json_response(payload):
    return io.BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


class StructuredCompletionTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(
            callable(getattr(enrollment, "request_completion_result", None)),
            "request_completion_result must expose structured single-attempt completions",
        )

    def complete(self, api_format="openai", **kwargs):
        return enrollment.request_completion_result(
            "https://example.test/v1", "fixture-secret", "fixture-model", "题目", None,
            api_format, **kwargs,
        )

    @patch("enrollment.urllib.request.urlopen")
    def test_openai_maps_usage_without_double_counting_reasoning(self, urlopen):
        urlopen.return_value = json_response(openai_response())

        self.assertEqual(self.complete(), {
            "text": "答案",
            "usage": {"input_tokens": 100, "output_tokens": 40, "reasoning_tokens": 25},
        })
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.test/v1/chat/completions")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer fixture-secret")
        self.assertEqual(json.loads(request.data), {
            "model": "fixture-model", "messages": [{"role": "user", "content": "题目"}],
        })
        self.assertEqual(urlopen.call_args.kwargs, {"timeout": 600})
        self.assertEqual(urlopen.call_count, 1)

    @patch("enrollment.urllib.request.urlopen")
    def test_anthropic_adds_reported_cache_inputs_once_and_extracts_text_blocks(self, urlopen):
        urlopen.return_value = json_response(anthropic_response())

        self.assertEqual(self.complete("anthropic", timeout=75), {
            "text": "答案",
            "usage": {"input_tokens": 150, "output_tokens": 40, "reasoning_tokens": None},
        })
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.test/v1/messages")
        self.assertEqual(request.get_header("X-api-key"), "fixture-secret")
        self.assertEqual(request.get_header("Anthropic-version"), "2023-06-01")
        self.assertEqual(json.loads(request.data), {
            "model": "fixture-model", "max_tokens": 4096,
            "messages": [{"role": "user", "content": "题目"}],
        })
        self.assertEqual(urlopen.call_args.kwargs, {"timeout": 75})

    @patch("enrollment.urllib.request.urlopen")
    def test_missing_null_and_invalid_usage_stay_nullable(self, urlopen):
        for api_format, factory in (("openai", openai_response), ("anthropic", anthropic_response)):
            for usage in ("missing", None, {}, {"prompt_tokens": None, "completion_tokens": None},
                          {"input_tokens": None, "output_tokens": None}):
                with self.subTest(api_format=api_format, usage=usage):
                    payload = factory()
                    if usage == "missing":
                        payload.pop("usage")
                    else:
                        payload["usage"] = usage
                    urlopen.return_value = json_response(payload)
                    self.assertEqual(self.complete(api_format)["usage"], {
                        "input_tokens": None, "output_tokens": None, "reasoning_tokens": None,
                    })

    @patch("enrollment.urllib.request.urlopen")
    def test_usage_rejects_negative_fractional_boolean_and_string_counts(self, urlopen):
        for invalid in (-1, 1.5, True, "12"):
            with self.subTest(invalid=invalid):
                payload = openai_response()
                payload["usage"] = {
                    "prompt_tokens": invalid, "completion_tokens": invalid,
                    "completion_tokens_details": {"reasoning_tokens": invalid},
                }
                urlopen.return_value = json_response(payload)
                self.assertEqual(self.complete()["usage"], {
                    "input_tokens": None, "output_tokens": None, "reasoning_tokens": None,
                })

    @patch("enrollment.urllib.request.urlopen")
    def test_real_zero_usage_is_preserved_for_both_protocols(self, urlopen):
        cases = (
            ("openai", openai_response, {
                "prompt_tokens": 0, "completion_tokens": 0,
                "completion_tokens_details": {"reasoning_tokens": 0},
            }, {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0}),
            ("anthropic", anthropic_response, {
                "input_tokens": 0, "output_tokens": 0,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            }, {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": None}),
        )
        for api_format, factory, usage, expected in cases:
            with self.subTest(api_format=api_format):
                payload = factory()
                payload["usage"] = usage
                urlopen.return_value = json_response(payload)
                self.assertEqual(self.complete(api_format)["usage"], expected)

    @patch("enrollment.urllib.request.urlopen")
    def test_anthropic_missing_cache_counts_do_not_invent_extra_usage(self, urlopen):
        payload = anthropic_response()
        payload["usage"] = {"input_tokens": 100, "output_tokens": 40}
        urlopen.return_value = json_response(payload)
        self.assertEqual(self.complete("anthropic")["usage"]["input_tokens"], 100)

    @patch("enrollment.urllib.request.urlopen")
    def test_openai_content_parts_are_combined_and_temperature_is_sent(self, urlopen):
        payload = openai_response()
        payload["choices"][0]["message"]["content"] = [
            {"type": "text", "text": "答"}, {"type": "text", "text": "案"},
        ]
        urlopen.return_value = json_response(payload)
        result = enrollment.request_completion_result(
            "https://example.test/v1/chat/completions", "fixture-secret", "fixture-model",
            "题目", 0, "openai",
        )
        self.assertEqual(result["text"], "答案")
        self.assertEqual(json.loads(urlopen.call_args.args[0].data)["temperature"], 0)
        self.assertEqual(urlopen.call_args.args[0].full_url, "https://example.test/v1/chat/completions")

    @patch("enrollment.time.sleep")
    @patch("enrollment.urllib.request.urlopen")
    def test_retryable_http_failure_makes_one_attempt_and_no_protocol_fallback(self, urlopen, sleep):
        urlopen.side_effect = urllib.error.HTTPError(
            "https://example.test/v1/chat/completions", 429, "Too Many Requests", {},
            io.BytesIO(b'{"error":{"message":"rate limited"}}'),
        )
        with self.assertRaisesRegex(RuntimeError, "HTTP 429: rate limited"):
            self.complete(max_attempts=1)
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(urlopen.call_args.args[0].full_url, "https://example.test/v1/chat/completions")
        sleep.assert_not_called()

    @patch("enrollment.time.sleep")
    @patch("enrollment.urllib.request.urlopen")
    def test_connection_failure_makes_one_attempt_with_custom_timeout(self, urlopen, sleep):
        urlopen.side_effect = urllib.error.URLError("timed out")
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            self.complete("anthropic", timeout=31)
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(urlopen.call_args.kwargs, {"timeout": 31})
        sleep.assert_not_called()

    @patch("enrollment.urllib.request.urlopen")
    def test_requires_explicit_supported_protocol_before_requesting(self, urlopen):
        for api_format in ("auto", "", "other", None):
            with self.subTest(api_format=api_format):
                with self.assertRaisesRegex(ValueError, "api_format"):
                    self.complete(api_format)
        urlopen.assert_not_called()

    @patch("enrollment.urllib.request.urlopen")
    def test_rejects_openai_refusal_truncation_and_filtering(self, urlopen):
        cases = (("length", None, "length"), ("content_filter", None, "content_filter"),
                 ("stop", "I cannot comply", "拒绝"))
        for finish_reason, refusal, error in cases:
            with self.subTest(finish_reason=finish_reason, refusal=refusal):
                payload = openai_response()
                payload["choices"][0]["finish_reason"] = finish_reason
                payload["choices"][0]["message"]["refusal"] = refusal
                urlopen.return_value = json_response(payload)
                with self.assertRaisesRegex(RuntimeError, error):
                    self.complete()

    @patch("enrollment.urllib.request.urlopen")
    def test_openai_failures_expose_partial_text_and_usage_as_typed_details(self, urlopen):
        expected_usage = {
            "input_tokens": 100, "output_tokens": 40, "reasoning_tokens": 25,
        }
        cases = (("length", None), ("content_filter", None), ("stop", "拒绝内容"))
        for finish_reason, refusal in cases:
            with self.subTest(finish_reason=finish_reason, refusal=refusal):
                payload = openai_response()
                payload["choices"][0]["finish_reason"] = finish_reason
                payload["choices"][0]["message"]["refusal"] = refusal
                payload["choices"][0]["message"]["content"] = "已生成的部分回答"
                urlopen.return_value = json_response(payload)
                with self.assertRaises(RuntimeError) as raised:
                    self.complete()
                self.assertEqual(raised.exception.details.text, "已生成的部分回答")
                self.assertEqual(raised.exception.details.usage, expected_usage)

    @patch("enrollment.urllib.request.urlopen")
    def test_anthropic_failures_expose_partial_text_and_usage_as_typed_details(self, urlopen):
        expected_usage = {
            "input_tokens": 150, "output_tokens": 40, "reasoning_tokens": None,
        }
        for stop_reason in ("refusal", "max_tokens"):
            with self.subTest(stop_reason=stop_reason):
                payload = anthropic_response()
                payload["stop_reason"] = stop_reason
                payload["content"] = [{"type": "text", "text": "已生成的部分回答"}]
                urlopen.return_value = json_response(payload)
                with self.assertRaises(RuntimeError) as raised:
                    self.complete("anthropic")
                self.assertEqual(raised.exception.details.text, "已生成的部分回答")
                self.assertEqual(raised.exception.details.usage, expected_usage)

    @patch("enrollment.urllib.request.urlopen")
    def test_api_failure_without_answer_or_usage_exposes_empty_typed_details(self, urlopen):
        payload = openai_response()
        payload["choices"][0]["finish_reason"] = "length"
        payload["choices"][0]["message"]["content"] = " \n\t"
        payload.pop("usage")
        urlopen.return_value = json_response(payload)

        with self.assertRaises(RuntimeError) as raised:
            self.complete()

        self.assertIsNone(raised.exception.details.text)
        self.assertIsNone(raised.exception.details.usage)

    @patch("enrollment.urllib.request.urlopen")
    def test_rejects_anthropic_refusal_and_truncation(self, urlopen):
        for stop_reason, error in (("refusal", "拒绝"), ("max_tokens", "截断")):
            with self.subTest(stop_reason=stop_reason):
                payload = anthropic_response()
                payload["stop_reason"] = stop_reason
                urlopen.return_value = json_response(payload)
                with self.assertRaisesRegex(RuntimeError, error):
                    self.complete("anthropic")

    @patch("enrollment.urllib.request.urlopen")
    def test_rejects_missing_response_structure_and_blank_answers(self, urlopen):
        for api_format, payload in (
            ("openai", {}), ("openai", {"choices": []}),
            ("openai", {"choices": [{"message": {"content": None}, "finish_reason": "stop"}]}),
            ("openai", {"choices": [{"message": {"content": "  "}, "finish_reason": "stop"}]}),
            ("anthropic", {"content": []}),
        ):
            with self.subTest(api_format=api_format, payload=payload):
                urlopen.return_value = json_response(payload)
                with self.assertRaises(RuntimeError):
                    self.complete(api_format)

    @patch("enrollment.urllib.request.urlopen")
    def test_normal_unanswerable_text_remains_a_successful_completion(self, urlopen):
        payload = openai_response()
        payload["choices"][0]["message"]["content"] = "无法回答"
        urlopen.return_value = json_response(payload)
        self.assertEqual(self.complete()["text"], "无法回答")

    @patch("enrollment.urllib.request.urlopen")
    def test_compacts_waf_errors_and_redacts_credentials_from_upstream_errors(self, urlopen):
        for details, expected in (
            (b"<html>Cloudflare Just a moment</html>", "Cloudflare/WAF"),
            (b'{"error":{"message":"invalid fixture-secret credential"}}', "invalid"),
        ):
            with self.subTest(details=details):
                urlopen.side_effect = urllib.error.HTTPError(
                    "https://example.test/v1/chat/completions", 403, "Forbidden", {}, io.BytesIO(details),
                )
                with self.assertRaises(RuntimeError) as raised:
                    self.complete()
                self.assertIn(expected, str(raised.exception))
                self.assertNotIn("fixture-secret", str(raised.exception))


class LegacyCompletionTests(unittest.TestCase):
    @patch("enrollment.time.sleep")
    @patch("enrollment.urllib.request.urlopen")
    def test_legacy_retries_connection_errors_then_returns_text_with_240_second_timeout(self, urlopen, sleep):
        urlopen.side_effect = [
            urllib.error.URLError("temporary"), urllib.error.URLError("temporary"),
            json_response(openai_response()),
        ]
        self.assertEqual(enrollment.request_completion(
            "https://example.test", "fixture-secret", "fixture-model", "题目", 0.5,
            "openai", "系统提示",
        ), "答案")
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        for call in urlopen.call_args_list:
            self.assertEqual(call.kwargs, {"timeout": 240})
            self.assertEqual(json.loads(call.args[0].data), {
                "model": "fixture-model", "temperature": 0.5,
                "messages": [{"role": "system", "content": "系统提示"}, {"role": "user", "content": "题目"}],
            })

    @patch("enrollment.urllib.request.urlopen")
    def test_legacy_auto_detects_anthropic_after_openai_failure(self, urlopen):
        urlopen.side_effect = [
            urllib.error.HTTPError("https://example.test", 404, "Not Found", {}, io.BytesIO(b"missing")),
            json_response(anthropic_response()),
        ]
        self.assertEqual(enrollment.request_completion(
            "https://example.test", "fixture-secret", "fixture-model", "题目", None,
        ), "答案")
        self.assertEqual([call.args[0].full_url for call in urlopen.call_args_list], [
            "https://example.test/v1/chat/completions", "https://example.test/v1/messages",
        ])

    @patch("enrollment.time.sleep")
    @patch("enrollment.urllib.request.urlopen")
    def test_legacy_exhausts_three_http_attempts_and_reports_retry_count(self, urlopen, sleep):
        urlopen.side_effect = [urllib.error.HTTPError(
            "https://example.test", 503, "Unavailable", {},
            io.BytesIO(b'{"error":{"message":"overloaded"}}'),
        ) for _ in range(3)]
        with self.assertRaisesRegex(RuntimeError, "HTTP 503: overloaded.*2"):
            enrollment.request_completion(
                "https://example.test", "fixture-secret", "fixture-model", "题目", None, "openai",
            )
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(sleep.call_count, 2)


class ApiProbeRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch("app.request_completion")
    def test_api_probe_keeps_existing_response_contract(self, request_completion):
        text = ", ".join(str(number) for number in range(1, 81))
        request_completion.return_value = text

        response = self.client.post(
            "/api/test/probe",
            json={
                "base_url": "https://example.test/v1",
                "api_key": "secret",
                "api_model": "model",
                "temperature": None,
                "prompt": "generate",
                "expected_count": 100,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "text": text,
                "parsed_numbers": 80,
                "minimum_numbers": 80,
                "accepted": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
