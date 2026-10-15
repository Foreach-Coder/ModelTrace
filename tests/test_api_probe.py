import unittest
from unittest.mock import patch

from app import app


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
