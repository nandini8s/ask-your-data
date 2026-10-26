# Evaluation questions and scoring

`questions.json` is the canonical evaluation set (`evals.json` at the project
root mirrors it for older scripts). Use `scoring.py` to normalize final answers
by lowercasing them and removing commas before matching expected phrases.

- An automatically scored answer must contain every phrase in `expected_all`.
- For every inner list in `expected_any`, it must contain at least one phrase
  from that list. Matching is substring matching on the normalized answer.
- `auto_score: false` entries are reviewed using their `manual_review` rubric.
- For question 18, the answer passes the row-cap check if it includes the first
  date and either the last date or an explicit notice that the result was
  truncated (for example, that only the first 50 rows are shown).

Date formatting is requested in the system prompt as `YYYY-MM-DD`. Numeric
expectations in questions that ask for rounded values use that requested
precision.

Run `python3 check_gold.py` from the project root to execute each available
`gold_sql` against `campus.db` in read-only mode and print its result. Questions
without `gold_sql` are skipped; SQL execution errors cause a non-zero exit code.
