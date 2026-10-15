import json
import unittest

from candy_testing import (
    CANDY_QUESTION_ID,
    DEFAULT_TIMEOUT_SECONDS,
    build_candy_result,
    grade_candy_answer,
    question_payload,
)


class GradeCandyAnswerTests(unittest.TestCase):
    def test_grades_valid_integer_answers_from_the_final_tag(self):
        cases = [
            ("推理过程没有数字。<final-answer>21</final-answer>", "correct", 21, "答案正确"),
            ("推理过程提到21。<final-answer>20</final-answer>", "incorrect", 20, "答案错误"),
            ("推理中有 21，但没有最终答案标签", "ungraded", None, "缺少最终答案标签"),
        ]
        for text, status, final_answer, reason in cases:
            with self.subTest(text=text):
                result = grade_candy_answer(text)
                self.assertEqual(result["status"], status)
                self.assertEqual(result["final_answer"], final_answer)
                self.assertEqual(result["grading_reason"], reason)

    def test_marks_malformed_final_answer_tags_ungraded(self):
        cases = [
            ("没有答案标签", "缺少最终答案标签"),
            ("<final-answer>21</final-answer><final-answer>21</final-answer>", "最终答案标签重复"),
            ("<final-answer note='x'>21</final-answer>", "最终答案标签不能带属性"),
            ("<final-answer>21", "最终答案标签未闭合"),
            ("<final-answer>21 <final-answer>22</final-answer></final-answer>", "最终答案标签不能嵌套"),
            ("<final-answer>21.0</final-answer>", "最终答案必须是整数"),
            ("<final-answer>21颗</final-answer>", "最终答案必须是整数"),
            ("<final-answer>21</final-answer>说明", "最终答案标签后只能有空白"),
        ]
        for text, reason in cases:
            with self.subTest(text=text):
                result = grade_candy_answer(text)
                self.assertEqual(result["status"], "ungraded")
                self.assertIsNone(result["final_answer"])
                self.assertEqual(result["grading_reason"], reason)
                self.assertEqual(result["answer"], text)

    def test_accepts_whitespace_around_tag_content_and_after_closing_tag(self):
        result = grade_candy_answer("  解题过程\n<final-answer> \n+21\t</final-answer> \n")
        self.assertEqual(result["status"], "correct")
        self.assertEqual(result["final_answer"], 21)

    def test_normal_unanswerable_text_is_ungraded_format_not_call_failure(self):
        result = grade_candy_answer("无法回答")
        self.assertEqual(result["status"], "ungraded")
        self.assertIsNone(result["final_answer"])
        self.assertEqual(result["grading_reason"], "缺少最终答案标签")

    def test_rejects_tag_variants_even_when_a_valid_pair_is_also_present(self):
        answers = [
            "<final-answer/>文本<final-answer>21</final-answer>",
            "<FINAL-ANSWER>20</FINAL-ANSWER><final-answer>21</final-answer>",
        ]
        for answer in answers:
            with self.subTest(answer=answer):
                result = grade_candy_answer(answer)
                self.assertEqual(result["status"], "ungraded")
                self.assertIsNone(result["final_answer"])

    def test_grades_very_long_decimal_answer_incorrect_without_integer_conversion_failure(self):
        result = grade_candy_answer(f"<final-answer>{'9' * 5000}</final-answer>")
        self.assertEqual(result["status"], "incorrect")
        self.assertIsNone(result["final_answer"])
        self.assertEqual(result["grading_reason"], "答案错误，整数过长未返回完整值")


class QuestionPayloadTests(unittest.TestCase):
    def test_exposes_question_identity_title_and_prompt_without_the_answer(self):
        payload = question_payload()
        self.assertEqual(set(payload), {"question_id", "title", "prompt"})
        self.assertEqual(payload["question_id"], "candy-v1")
        self.assertTrue(payload["title"])
        self.assertEqual(
            payload["prompt"],
            """不使用任何外部工具回答以下问题：

在一个黑色的袋子里放有三种口味的糖果，每种糖果有两种不同的形状（圆形和五角星形，不同的形状靠手感可以分辨）。现已知不同口味的糖和不同形状的数量统计如下表。参赛者需要在活动前决定摸出的糖果数目，那么，最少取出多少个糖果才能保证手中同时拥有不同形状的苹果味和桃子味的糖？（同时手中有圆形苹果味匹配五角星桃子味糖果，或者有圆形桃子味匹配五角星苹果味糖果都满足要求）

        苹果味  桃子味  西瓜味
圆形       7      9      8
五角星形   7      6      4

请给出解题过程，并在回答最后使用 <final-answer>整数</final-answer> 输出最终答案。该标签只能出现一次，标签内不要包含单位、解释或其他内容。
""",
        )
        self.assertNotIn("标准答案", payload)
        self.assertNotIn("21", payload["prompt"])
        self.assertEqual(CANDY_QUESTION_ID, "candy-v1")
        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, 600)


class BuildCandyResultTests(unittest.TestCase):
    def test_build_result_for_very_long_integer_is_json_serializable(self):
        answer = f"<final-answer>{'9' * 5000}</final-answer>"
        result = build_candy_result(answer, None, 1)
        serialized = json.dumps(result)
        decoded = json.loads(serialized)
        self.assertEqual(decoded["status"], "incorrect")
        self.assertIsNone(decoded["final_answer"])
        self.assertEqual(decoded["grading_reason"], "答案错误，整数过长未返回完整值")

    def test_preserves_nullable_usage_and_builds_tps_for_valid_counts_and_time(self):
        usage = {"input_tokens": None, "output_tokens": 12, "reasoning_tokens": None}
        result = build_candy_result("<final-answer>21</final-answer>", usage, 3)
        self.assertEqual(result["question_id"], "candy-v1")
        self.assertEqual(result["status"], "correct")
        self.assertEqual(result["answer"], "<final-answer>21</final-answer>")
        self.assertEqual(result["final_answer"], 21)
        self.assertEqual(result["grading_reason"], "答案正确")
        self.assertEqual(result["usage"], usage)
        self.assertEqual(result["elapsed_seconds"], 3)
        self.assertEqual(result["tps"], 4.0)
        self.assertIsNone(result["error"])

    def test_reports_no_tps_without_valid_output_tokens_and_positive_elapsed_time(self):
        cases = [
            ({"input_tokens": 2, "output_tokens": None, "reasoning_tokens": None}, 2),
            ({"input_tokens": 2, "output_tokens": 10, "reasoning_tokens": None}, None),
            ({"input_tokens": 2, "output_tokens": 10, "reasoning_tokens": None}, 0),
            ({"input_tokens": 2, "output_tokens": -1, "reasoning_tokens": None}, 2),
        ]
        for usage, elapsed_seconds in cases:
            with self.subTest(usage=usage, elapsed_seconds=elapsed_seconds):
                result = build_candy_result("<final-answer>20</final-answer>", usage, elapsed_seconds)
                self.assertIsNone(result["tps"])
                self.assertEqual(result["usage"], usage)

    def test_preserves_zero_output_tokens_as_zero_tps(self):
        result = build_candy_result(
            "<final-answer>20</final-answer>",
            {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0},
            4,
        )
        self.assertEqual(result["tps"], 0.0)


if __name__ == "__main__":
    unittest.main()
