# Ask Your Data

Ask natural-language questions about campus electricity use and get answers
through a Python agent that asks Gemini to call read-only SQLite tools. The
campus readings and events are synthetic data generated locally for this project.

## Demo

**Screenshot or GIF:** no demo asset is committed yet; add one here when available.

## Results

The most recently confirmed live run was a **partial evaluation** on
2026-11-11 using `gemini-3.5-flash-lite`. It scored questions 1–10, then stopped
at question 11 when Gemini returned HTTP 429.

| Measure | Result |
| --- | --- |
| Development questions | 8/8 passed (100%, n=8) |
| Test questions | 2/2 passed (100%, n=2) |
| Overall automated accuracy | 10/10 passed (100%, n=10) |
| Manual-review cases in the dataset | 9 (none in questions 1–10) |
| API errors in this run | 1 rate limit (HTTP 429) |

These figures describe only the ten scored questions in that partial run; they
are not full development-set, test-set, or dataset results. The most recent run
had no automatically scored answer failures. Historical JSONL records include
two Q22 scoring failures: the answers correctly said that Sports Complex was
absent, but an earlier expected-phrase list did not accept those equivalent
wordings. The current Q22 expectations include those phrasings. A previous
sandboxed evaluation attempt also recorded API connection errors because it
could not reach Gemini; that attempt is not included in the table above.

## Example Questions

- How many readings are in the database?
- Which building used the most electricity over the full period?
- When does the Annual tech fest start?
- What was the Library's average use during Mid-semester exams overnight?
- Compare CS Lab Block use at night and during daytime hours.

## How It Works

Streamlit provides the chat UI and retains a bounded conversation. `loop.py`
sends the recent user and assistant messages, tool definitions, and system
instructions to Gemini through its OpenAI-compatible API. The agent can call
`get_schema` to inspect tables and `run_sql` to execute a read-only SQLite query.
The model sees tool results and returns a natural-language answer. The UI keeps
the tool trace available for inspection.

## Design Decisions

- Schema inspection gives the model the actual table and column names before it
  writes SQL.
- The system prompt and tool definitions specify SQLite syntax and the expected
  query behavior.
- The model calls explicit tools; it has no direct database connection.
- API and tool errors are recorded separately from automatically scored wrong
  answers.
- Evaluation questions carry phrase and ordered numeric expectations. Some
  ambiguity and safety cases require manual review rather than a guessed score.

## SQL Safety

- `campus.db` is opened with SQLite's read-only URI mode and `query_only` enabled.
- The authorizer permits query/read/function actions and denies writes, schema
  changes, attachment operations, pragmas, and selected unsafe functions.
- Only a single `SELECT` or read-only `WITH` query is accepted.
- A SQLite progress handler interrupts long-running queries after two seconds.
- Results are capped at 50 rows, and SQL errors returned to the model omit paths
  and internal exception details.

## Setup

A fresh clone does not include `campus.db`; it is ignored by Git and generated
locally. The first run is:

```sh
python3 -m pip install -r requirements.txt
python3 make_db.py
streamlit run streamlit_app.py
```

Set these values in `.env` before asking questions that use Gemini:

```dotenv
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.5-flash-lite
```

`GEMINI_MODEL` is optional; the application fallback is
`gemini-3.5-flash-lite`. The generator refuses to overwrite an existing database.
Use `python3 make_db.py --force` only when you explicitly intend to replace the
generated local database.

## Run Evaluations

`run_evals.py` uses the live Gemini API and may incur API usage. Without a scope
argument, it runs the full evaluation set. Start with selected IDs or one split:

```sh
python3 run_evals.py --ids 1 2
python3 run_evals.py --split dev
python3 run_evals.py --split test --sleep 1
```

Use `--model MODEL` to select another model, and `--output PATH` to append a run
to a separate JSONL file. The default file is
`evals/results_<model>.jsonl`. Result files are append-only; each record contains
the model, UTC timestamp, question metadata, status, answer, tool trace, turns,
and error. Each invocation reports only its own results and labels selected
subsets or interrupted runs **PARTIAL**. Automated accuracy is
`passed / (passed + failed)`; manual-review cases and API errors are excluded.

## Automated Tests

Install the development dependency and run the deterministic suite:

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m pytest
```

Tests use temporary databases and mocked model responses; they do not call
Gemini or modify the local campus database.

## Limitations

Ambiguity handling is guided by the model prompt rather than a deterministic
classifier. The generated readings are synthetic, so results do not represent
real campus operations. The most recent live evaluation was partial due to API
rate limiting; full-set accuracy remains unverified.
