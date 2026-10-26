"""Phrase-based scoring helpers for ``evals/questions.json``."""


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

    return {
        "passed": not missing_all and not unsatisfied_any,
        "missing_all": missing_all,
        "unsatisfied_any": unsatisfied_any,
    }
