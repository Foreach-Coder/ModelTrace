import unittest

from automatic_testing import evaluate_probe


class EvaluateProbeTests(unittest.TestCase):
    def test_accepts_output_at_minimum_number_threshold(self):
        text = ", ".join(str(number) for number in range(1, 81))

        self.assertEqual(
            evaluate_probe(text, 100),
            {
                "text": text,
                "parsed_numbers": 80,
                "minimum_numbers": 80,
                "accepted": True,
            },
        )

    def test_rejects_output_below_minimum_number_threshold(self):
        text = ", ".join(str(number) for number in range(1, 80))

        result = evaluate_probe(text, 100)

        self.assertEqual(result["parsed_numbers"], 79)
        self.assertEqual(result["minimum_numbers"], 80)
        self.assertFalse(result["accepted"])

    def test_rejects_non_positive_expected_count(self):
        with self.assertRaisesRegex(ValueError, "expected_count"):
            evaluate_probe("1, 2, 3", 0)


if __name__ == "__main__":
    unittest.main()
