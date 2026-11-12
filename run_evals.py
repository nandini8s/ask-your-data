"""Run selected live evaluations and append each result as JSONL."""

import argparse
import json
import re
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from evals.scoring import score_answer
from loop import MODEL, run_loop


PROJECT_DIR = Path(__file__).resolve().parent
QUESTIONS_PATH = PROJECT_DIR / "evals" / "questions.json"
DATABASE_PATH = PROJECT_DIR / "campus.db"
EXPECTED_READING_COUNT = 11520
COUNT_CHECK_IDS = {21, 30, 35}


def load_questions(path=QUESTIONS_PATH):
    with path.open(encoding="utf-8") as questions_file:
        questions = json.load(questions_file)
    if not isinstance(questions, list):
        raise ValueError("The questions file must contain a JSON list.")
    return questions


def _result_path(model):
    safe_model = re.sub(r"[^A-Za-z0-9_.-]+", "_", model)
    return PROJECT_DIR / "evals" / f"results_{safe_model}.jsonl"


def _readings_count():
    uri = DATABASE_PATH.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        return connection.execute("SELECT COUNT(*) FROM readings").fetchone()[0]


def _accuracy_stats(results):
    passed = sum(result["status"] == "passed" for result in results)
    failed = sum(result["status"] == "failed" for result in results)
    scored = passed + failed
    return {
        "passed": passed,
        "failed": failed,
        "scored": scored,
        "accuracy_percent": (passed / scored * 100) if scored else None,
    }


def _print_accuracy(label, stats):
    if stats["scored"] == 0:
        print(f"{label}: n/a (0 scored; 0 passed, 0 failed)")
    else:
        print(
            f"{label}: {stats['passed']}/{stats['scored']} "
            f"({stats['accuracy_percent']:.1f}%; n={stats['scored']}; "
            f"{stats['failed']} failed)"
        )


def _print_summary(results, selected_count, partial, failure_reason=None):
    if failure_reason:
        run_status = "FAILED"
    else:
        run_status = "PARTIAL" if partial else "COMPLETE"
    print(
        f"\nRun status: {run_status} "
        f"({len(results)}/{selected_count} selected questions processed)"
    )
    if failure_reason:
        print(f"Run failure: {failure_reason}")
    _print_accuracy("Overall automated accuracy", _accuracy_stats(results))
    for split in ("dev", "test"):
        split_results = [result for result in results if result.get("split") == split]
        _print_accuracy(f"{split} automated accuracy", _accuracy_stats(split_results))

    manual_reviews = sum(result["status"] == "needs_review" for result in results)
    api_errors = sum(
        result["status"] == "api_error" or result.get("error") is not None
        for result in results
    )
    interrupted = max(0, selected_count - len(results))
    turns = [result["turns"] for result in results if isinstance(result.get("turns"), (int, float))]
    print("Manual-review-only questions:", manual_reviews)
    print("API/agent errors:", api_errors)
    print("Interrupted / unattempted questions:", interrupted)
    print("Average turns:", f"{sum(turns) / len(turns):.2f}" if turns else "n/a")

    groups = defaultdict(list)
    for result in results:
        groups[result.get("group") or "unspecified"].append(result)
    print("Accuracy by question group:")
    for group in sorted(groups):
        _print_accuracy(f"  {group}", _accuracy_stats(groups[group]))


def run_evals(questions, model=MODEL, ids=None, split=None, sleep_seconds=0.0, output_path=None):
    selected = questions
    if ids:
        id_set = set(ids)
        selected = [question for question in selected if question.get("id") in id_set]
        missing_ids = id_set - {question.get("id") for question in selected}
        if missing_ids:
            raise ValueError(f"Question IDs not found: {', '.join(map(str, sorted(missing_ids)))}")
    if split:
        selected = [question for question in selected if question.get("split") == split]

    output_path = output_path or _result_path(model)
    results = []
    failure_reason = None
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as results_file:
        for index, question in enumerate(selected, start=1):
            question_id = question.get("id")
            print(f"[{index}/{len(selected)}] Q{question_id}: {question['question']}", flush=True)
            response = run_loop(
                question["question"],
                model=model,
                conversation_history=question.get("conversation_history"),
            )
            error = response.get("error")
            if error is not None:
                status = "api_error"
                score = None
            elif not question.get("auto_score", True):
                status = "needs_review"
                score = score_answer(question, response.get("answer", ""))
            else:
                score = score_answer(question, response.get("answer", ""))
                status = "passed" if score["passed"] else "failed"

            record = {
                "model": model,
                "timestamp": timestamp,
                "id": question_id,
                "group": question.get("group"),
                "split": question.get("split"),
                "question": question["question"],
                "answer": response.get("answer", ""),
                "status": status,
                "score": score,
                "error": error,
                "tool_calls": response.get("tool_calls", []),
                "turns": response.get("turns"),
            }
            results_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            results_file.flush()
            results.append(record)
            print(f"  {status}: {record['answer'] or error or ''}", flush=True)

            if question_id in COUNT_CHECK_IDS:
                count = _readings_count()
                if count != EXPECTED_READING_COUNT:
                    failure_reason = (
                        f"Readings integrity check failed after question {question_id}: "
                        f"expected {EXPECTED_READING_COUNT}, found {count}."
                    )
                    print(f"  INTEGRITY CHECK FAILED: {failure_reason}", flush=True)
                    break
                print(f"  readings integrity check: {count}", flush=True)

            if record["status"] == "api_error":
                failure_reason = f"Evaluation stopped after API/agent error: {record['error']}."
                print(
                    f"Stopping evaluation after API/agent error: {record['error']}.",
                    flush=True,
                )
                break
            if sleep_seconds > 0 and index < len(selected):
                time.sleep(sleep_seconds)

    partial = len(selected) != len(questions) or len(results) != len(selected)
    _print_summary(results, len(selected), partial, failure_reason)
    print(f"Results appended to {output_path}")
    return results


def main():
    parser = argparse.ArgumentParser(description="Run the campus database evaluation questions.")
    parser.add_argument("--ids", nargs="+", type=int, help="Question IDs to run.")
    parser.add_argument("--split", choices=("dev", "test"), help="Run only this split.")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to wait between questions.")
    parser.add_argument("--model", default=MODEL, help="Model name (defaults to GEMINI_MODEL).")
    parser.add_argument(
        "--output",
        type=Path,
        help="Append results to this JSONL file instead of the model's default file.",
    )
    args = parser.parse_args()
    if args.sleep < 0:
        parser.error("--sleep must be zero or greater")

    try:
        questions = load_questions()
        run_evals(
            questions,
            args.model,
            args.ids,
            args.split,
            args.sleep,
            args.output,
        )
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError, sqlite3.Error) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
