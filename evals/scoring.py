"""Phrase-based scoring helpers for ``evals/questions.json``."""

import re


def normalize_answer(answer):
    """Apply the normalization used by the evaluation phrase matcher."""
    return str(answer).lower().replace(",", "")


def score_answer(question, answer):
    """Score an answer, or return ``passed=None`` for manual-review questions."""
    if not question.get("auto_score", True):
        return {
            "passed": None,
            "manual_review": question.get("manual_review"),
        }

    normalized = normalize_answer(answer)
    missing_all = [
        phrase
        for phrase in question.get("expected_all", [])
        if normalize_answer(phrase) not in normalized
    ]
    unsatisfied_any = [
        alternatives
        for alternatives in question.get("expected_any", [])
        if not any(normalize_answer(phrase) in normalized for phrase in alternatives)
    ]
    actual_numbers = [float(value) for value in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", normalized)]
    missing_numbers = []
    number_cursor = 0
    for expected in question.get("expected_numbers", []):
        precision = len(str(expected).partition(".")[2])
        tolerance = 0.051 if precision == 1 else 0.0051
        match_index = next(
            (
                index
                for index in range(number_cursor, len(actual_numbers))
                if abs(actual_numbers[index] - float(expected)) <= tolerance
            ),
            None,
        )
        if match_index is None:
            missing_numbers.append(expected)
        else:
            number_cursor = match_index + 1

    return {
        "passed": not missing_all and not unsatisfied_any and not missing_numbers,
        "missing_all": missing_all,
        "unsatisfied_any": unsatisfied_any,
        "missing_numbers": missing_numbers,
    }
