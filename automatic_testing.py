from __future__ import annotations

import math

from fingerprint import parse_numbers


def evaluate_probe(text: str, expected_count: int) -> dict[str, object]:
    if expected_count <= 0:
        raise ValueError("expected_count 必须是正整数")
    parsed_numbers = len(parse_numbers(text))
    minimum_numbers = max(80, math.ceil(expected_count * 0.55))
    return {
        "text": text,
        "parsed_numbers": parsed_numbers,
        "minimum_numbers": minimum_numbers,
        "accepted": parsed_numbers >= minimum_numbers,
    }
