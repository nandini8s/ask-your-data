import argparse
import json
import math
import sqlite3
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_QUESTIONS = PROJECT_DIR / "evals" / "questions.json"
DEFAULT_DATABASE = PROJECT_DIR / "campus.db"


def load_questions(path):
    with path.open(encoding="utf-8") as questions_file:
        questions = json.load(questions_file)
    if not isinstance(questions, list):
        raise ValueError("The questions file must contain a JSON list.")
    return questions


def _flatten_rows(rows):
    for row in rows:
        for value in row:
            if isinstance(value, (tuple, list)):
                yield from value
            else:
                yield value


def _missing_expected_numbers(expected_numbers, rows):
    actual_numbers = [
        value
        for value in _flatten_rows(rows)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    return [
        expected
        for expected in expected_numbers
        if not any(
            math.isclose(float(expected), float(actual), rel_tol=0.0, abs_tol=1e-9)
            for actual in actual_numbers
        )
    ]


def check_gold(questions_path, database_path):
    questions = load_questions(questions_path)
    database_uri = database_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(database_uri, uri=True)
    failures = 0
    skipped = 0

    try:
        for question in questions:
            question_id = question.get("id", "?")
            sql = question.get("gold_sql")
            if not sql:
                skipped += 1
                print(f"SKIP {question_id}: no gold SQL")
                continue

            try:
                rows = connection.execute(sql).fetchall()
            except sqlite3.Error as error:
                failures += 1
                print(f"FAIL {question_id}: {error}")
                continue

            expected_numbers = question.get("expected_numbers", [])
            missing_numbers = _missing_expected_numbers(expected_numbers, rows)
            if missing_numbers:
                failures += 1
                print(
                    f"FAIL {question_id}: expected numeric values "
                    f"{missing_numbers} not found in gold result {json.dumps(rows)}"
                )
                continue

            print(f"PASS {question_id}: {json.dumps(rows)}")
    finally:
        connection.close()

    checked = len(questions) - skipped
    print(f"\nChecked {checked} gold queries; {failures} failed, {skipped} skipped.")
    return failures == 0


def main():
    parser = argparse.ArgumentParser(
        description="Run the evaluation set's gold SQL against the campus database."
    )
    parser.add_argument(
        "--questions",
        type=Path,
        default=DEFAULT_QUESTIONS,
        help=f"Evaluation JSON file (default: {DEFAULT_QUESTIONS})",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help=f"SQLite database file (default: {DEFAULT_DATABASE})",
    )
    args = parser.parse_args()

    try:
        success = check_gold(args.questions, args.database)
    except (OSError, json.JSONDecodeError, sqlite3.Error, ValueError) as error:
        parser.error(str(error))

    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
