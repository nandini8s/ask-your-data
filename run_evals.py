"""Run selected live evaluations and append each result as JSONL."""

import argparse
import json
import re
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

from evals.scoring import score_answer
from loop import MODEL, run_loop


PROJECT_DIR = Path(__file__).resolve().parent
QUESTIONS_PATH = PROJECT_DIR / "evals" / "questions.json"
DATABASE_PATH = PROJECT_DIR / "campus.db"
EXPECTED_READING_COUNT = 11520
COUNT_CHECK_IDS = {21, 30}


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


def _print_summary(results):
    scored = [
        result for result in results
        if result["status"] in ("passed", "failed")
    ]
    passed = sum(result["status"] == "passed" for result in scored)
    accuracy = f"{passed}/{len(scored)} ({passed / len(scored):.1%})" if scored else "n/a (0 scored)"
    turns = [result["turns"] for result in results if isinstance(result.get("turns"), (int, float))]
    average_turns = f"{sum(turns) / len(turns):.2f}" if turns else "n/a"
    api_errors = sum(result.get("error") is not None for result in results)

    print("\nAccuracy overall:", accuracy)
    print("Average turns:", average_turns)
    print("API errors:", api_errors)
    groups = defaultdict(list)
    for result in scored:
        groups[result["group"]].append(result)
    print("Accuracy by group:")
    for group in sorted(groups):
        group_results = groups[group]
        group_passed = sum(result["status"] == "passed" for result in group_results)
        print(f"  {group}: {group_passed}/{len(group_results)} ({group_passed / len(group_results):.1%})")


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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as results_file:
        for index, question in enumerate(selected, start=1):
            question_id = question.get("id")
            print(f"[{index}/{len(selected)}] Q{question_id}: {question['question']}", flush=True)
            response = run_loop(question["question"], model=model)
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
                    raise RuntimeError(
                        f"Readings integrity check failed after question {question_id}: "
                        f"expected {EXPECTED_READING_COUNT}, found {count}."
                    )
                print(f"  readings integrity check: {count}", flush=True)

            if record["error"] == "rate_limited":
                print("Stopping evaluation: API rate limit (429) encountered.", flush=True)
                break
            if sleep_seconds > 0 and index < len(selected):
                time.sleep(sleep_seconds)

    _print_summary(results)
    print(f"Results appended to {output_path}")
    return results


def main():
    parser = argparse.ArgumentParser(description="Run the campus database evaluation questions.")
    parser.add_argument("--ids", nargs="+", type=int, help="Question IDs to run.")
    parser.add_argument("--split", choices=("dev", "test"), help="Run only this split.")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to wait between questions.")
    parser.add_argument("--model", default=MODEL, help="Model name (defaults to GEMINI_MODEL).")
    args = parser.parse_args()
    if args.sleep < 0:
        parser.error("--sleep must be zero or greater")

    try:
        questions = load_questions()
        run_evals(questions, args.model, args.ids, args.split, args.sleep)
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError, sqlite3.Error) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
