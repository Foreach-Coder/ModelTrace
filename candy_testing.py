import math
import re


CANDY_QUESTION_ID = "candy-v1"
DEFAULT_TIMEOUT_SECONDS = 600
_MAX_JSON_SAFE_INTEGER_DIGITS = 4000

_TITLE = "最少需要取出多少颗糖果？"
_PROMPT = """不使用任何外部工具回答以下问题：

在一个黑色的袋子里放有三种口味的糖果，每种糖果有两种不同的形状（圆形和五角星形，不同的形状靠手感可以分辨）。现已知不同口味的糖和不同形状的数量统计如下表。参赛者需要在活动前决定摸出的糖果数目，那么，最少取出多少个糖果才能保证手中同时拥有不同形状的苹果味和桃子味的糖？（同时手中有圆形苹果味匹配五角星桃子味糖果，或者有圆形桃子味匹配五角星苹果味糖果都满足要求）

        苹果味  桃子味  西瓜味
圆形       7      9      8
五角星形   7      6      4

请给出解题过程，并在回答最后使用 <final-answer>整数</final-answer> 输出最终答案。该标签只能出现一次，标签内不要包含单位、解释或其他内容。
"""


def question_payload() -> dict[str, str]:
    return {
        "question_id": CANDY_QUESTION_ID,
        "title": _TITLE,
        "prompt": _PROMPT,
    }


def grade_candy_answer(text: str) -> dict[str, object]:
    answer = text
    opening = "<final-answer>"
    closing = "</final-answer>"
    attribute_tags = re.findall(r"<final-answer(?=[\t\r\n ])[^>]*>", text)
    if attribute_tags:
        return _grading_result(answer, None, "ungraded", "最终答案标签不能带属性")

    tag_matches = list(
        re.finditer(r"</?\s*final-answer\b[^<>]*(?:>|(?=<|$))", text, re.IGNORECASE)
    )
    if any(match.group() not in (opening, closing) for match in tag_matches):
        return _grading_result(answer, None, "ungraded", "最终答案标签格式无效")

    openings = [match.start() for match in re.finditer(re.escape(opening), text)]
    closings = [match.start() for match in re.finditer(re.escape(closing), text)]
    tokens = sorted([(position, "open") for position in openings] + [(position, "close") for position in closings])
    depth = 0
    nested = False
    for _, kind in tokens:
        if kind == "open":
            if depth:
                nested = True
            depth += 1
        elif depth:
            depth -= 1
    if nested:
        return _grading_result(answer, None, "ungraded", "最终答案标签不能嵌套")
    if not openings:
        return _grading_result(answer, None, "ungraded", "缺少最终答案标签")
    if len(openings) > 1 or len(closings) > 1:
        if len(openings) > len(closings):
            reason = "最终答案标签未闭合"
        else:
            reason = "最终答案标签重复"
        return _grading_result(answer, None, "ungraded", reason)
    if not closings or openings[0] > closings[0]:
        return _grading_result(answer, None, "ungraded", "最终答案标签未闭合")

    content = text[openings[0] + len(opening):closings[0]].strip()
    if not re.fullmatch(r"[+-]?[0-9]+", content):
        return _grading_result(answer, None, "ungraded", "最终答案必须是整数")
    if text[closings[0] + len(closing):].strip():
        return _grading_result(answer, None, "ungraded", "最终答案标签后只能有空白")

    is_negative = content.startswith("-")
    digits = content.lstrip("+-")
    normalized_digits = digits.lstrip("0") or "0"
    if len(normalized_digits) > _MAX_JSON_SAFE_INTEGER_DIGITS:
        return _grading_result(answer, None, "incorrect", "答案错误，整数过长未返回完整值")

    normalized_content = ("-" if is_negative and normalized_digits != "0" else "") + normalized_digits
    final_answer = _parse_decimal_integer(normalized_content)
    if final_answer == 21:
        return _grading_result(answer, final_answer, "correct", "答案正确")
    return _grading_result(answer, final_answer, "incorrect", "答案错误")


def _parse_decimal_integer(content: str) -> int:
    sign = -1 if content.startswith("-") else 1
    digits = content[1:] if content[:1] in ("+", "-") else content
    value = 0
    chunk_size = 1000
    for offset in range(0, len(digits), chunk_size):
        chunk = digits[offset:offset + chunk_size]
        value = value * (10 ** len(chunk)) + int(chunk, 10)
    return sign * value


def build_candy_result(
    text: str,
    usage: dict[str, object] | None,
    elapsed_seconds: int | float | None,
) -> dict[str, object]:
    grading = grade_candy_answer(text)
    output_tokens = usage.get("output_tokens") if usage is not None else None
    valid_tokens = type(output_tokens) is int and output_tokens >= 0
    valid_elapsed = (
        type(elapsed_seconds) in (int, float)
        and elapsed_seconds > 0
        and math.isfinite(float(elapsed_seconds))
    )
    tps = output_tokens / elapsed_seconds if valid_tokens and valid_elapsed else None
    return {
        "question_id": CANDY_QUESTION_ID,
        **grading,
        "usage": usage,
        "elapsed_seconds": elapsed_seconds,
        "tps": tps,
        "error": None,
    }


def _grading_result(answer: str, final_answer: int | None, status: str, reason: str) -> dict[str, object]:
    return {
        "answer": answer,
        "final_answer": final_answer,
        "status": status,
        "grading_reason": reason,
    }
