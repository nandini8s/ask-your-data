import json
import sqlite3
from types import SimpleNamespace

import pytest

import tools
from check_gold import check_gold
from make_db import create_database
from evals.scoring import score_answer
from loop import execute_tool, normalize_conversation_history, run_loop
import run_evals


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE readings (id INTEGER PRIMARY KEY, kwh REAL);"
            "INSERT INTO readings (kwh) VALUES "
            + ",".join(f"({value})" for value in range(60))
        )
    monkeypatch.setattr(tools, "DB_PATH", path)
    return path


def test_database_generator_creates_expected_dataset_and_refuses_overwrite(tmp_path):
    path = tmp_path / "generated.db"
    assert create_database(path) == path.resolve()
    assert check_gold(run_evals.QUESTIONS_PATH, path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM buildings").fetchone() == (8,)
        assert connection.execute("SELECT COUNT(*) FROM readings").fetchone() == (11520,)
        before = connection.execute("SELECT kwh FROM readings ORDER BY id LIMIT 1").fetchone()

    with pytest.raises(FileExistsError):
        create_database(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM readings").fetchone() == (11520,)
        assert connection.execute("SELECT kwh FROM readings ORDER BY id LIMIT 1").fetchone() == before

    create_database(path, overwrite=True)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM readings").fetchone() == (11520,)
        assert connection.execute("SELECT kwh FROM readings ORDER BY id LIMIT 1").fetchone() == before


@pytest.mark.parametrize(
    "action",
    [sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION],
)
def test_read_only_authorizer_allows_query_actions(action):
    assert tools._read_only_authorizer(action, None, None, "main", None) == sqlite3.SQLITE_OK


@pytest.mark.parametrize(
    "action",
    [
        sqlite3.SQLITE_INSERT,
        sqlite3.SQLITE_UPDATE,
        sqlite3.SQLITE_DELETE,
        sqlite3.SQLITE_DROP_TABLE,
        sqlite3.SQLITE_ALTER_TABLE,
        sqlite3.SQLITE_ATTACH,
        sqlite3.SQLITE_DETACH,
        sqlite3.SQLITE_PRAGMA,
    ],
)
def test_read_only_authorizer_denies_mutating_actions(action):
    assert tools._read_only_authorizer(action, None, None, "main", None) == sqlite3.SQLITE_DENY


@pytest.mark.parametrize("function_name", ["load_extension", "writefile", "readfile"])
def test_read_only_authorizer_denies_unsafe_functions(function_name):
    result = tools._read_only_authorizer(
        sqlite3.SQLITE_FUNCTION,
        None,
        function_name,
        "main",
        None,
    )
    assert result == sqlite3.SQLITE_DENY


def test_read_only_authorizer_allows_ordinary_function():
    result = tools._read_only_authorizer(
        sqlite3.SQLITE_FUNCTION,
        None,
        "SUM",
        "main",
        None,
    )
    assert result == sqlite3.SQLITE_OK


def test_select_queries_are_read_only_and_limited(database):
    result = tools.run_sql("SELECT id, kwh FROM readings ORDER BY id")
    assert "(1, 0.0)" in result
    assert "(50, 49.0)" in result
    assert "(51, 50.0)" not in result
    assert "Showing first 50 rows" in result

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM readings").fetchone() == (60,)


def test_load_extension_query_is_rejected_by_authorizer(database):
    assert tools.run_sql("SELECT load_extension('example')") == (
        "Error: only read-only SELECT queries are allowed"
    )


@pytest.mark.parametrize(
    "query",
    [
        "INSERT INTO readings (kwh) VALUES (999)",
        "UPDATE readings SET kwh = 0",
        "DELETE FROM readings",
        "DROP TABLE readings",
        "ALTER TABLE readings ADD COLUMN unsafe TEXT",
        "CREATE TABLE unsafe (id INTEGER)",
        "ATTACH DATABASE ':memory:' AS other",
        "DETACH DATABASE other",
        "PRAGMA table_info(readings)",
        "/* comment */ DELETE FROM readings",
        "; SELECT 1",
        "WITH removed AS (DELETE FROM readings RETURNING id) SELECT * FROM removed",
    ],
)
def test_unsafe_sql_is_rejected(database, query):
    result = tools.run_sql(query)
    assert result.startswith("Error:")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM readings").fetchone() == (60,)


def test_multiple_statements_are_rejected(database):
    result = tools.run_sql("SELECT 1; DROP TABLE readings")
    assert "one SELECT" in result
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM readings").fetchone() == (60,)


def test_comments_and_trailing_semicolon_are_supported(database):
    assert "Rows: [(1,)]" in tools.run_sql("-- leading comment\nSELECT 1;")
    assert "Rows: [(1,)]" in tools.run_sql("/* leading comment */ SELECT 1")


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("SELECT * FROM missing_table", "Error: no such table referenced in query"),
        ("SELECT missing_column FROM readings", "Error: no such column referenced in query"),
        (
            "SELECT id FROM readings AS first JOIN readings AS second ON first.id = second.id",
            "Error: ambiguous column name in query",
        ),
        ("SELECT * FORM readings", "Error: SQL syntax error"),
    ],
)
def test_recoverable_sql_errors_are_useful_and_safe(database, query, expected):
    assert tools.run_sql(query) == expected


def test_sql_error_does_not_reveal_paths_or_secrets(database, monkeypatch):
    sentinel = "PRIVATE_DB_PATH_AND_API_KEY_SENTINEL"
    monkeypatch.setenv("GEMINI_API_KEY", sentinel)
    result = tools.run_sql(f'SELECT * FROM "{sentinel}"')
    assert result == "Error: no such table referenced in query"
    assert sentinel not in result
    assert str(database) not in result


def test_query_timeout(database, monkeypatch):
    monkeypatch.setattr(tools, "QUERY_TIMEOUT_SECONDS", 0.01)
    result = tools.run_sql(
        "WITH RECURSIVE counter(value) AS (VALUES(1) UNION ALL "
        "SELECT value + 1 FROM counter WHERE value < 1000000000) "
        "SELECT SUM(value) FROM counter"
    )
    assert result == "Error: query exceeded the time limit"


def test_tool_arguments_are_validated():
    assert execute_tool("run_sql", {}) == "Error: invalid arguments for run_sql"
    assert execute_tool("run_sql", {"query": 123}) == "Error: query must be a non-empty SQL string"
    assert execute_tool("get_schema", {"unexpected": True}) == "Error: invalid arguments for get_schema"


def test_conversation_history_is_bounded_filtered_and_ordered():
    history = [{"role": "user", "content": f"old-{index}"} for index in range(12)]
    history += [{"role": "tool", "content": "raw SQL output"}, {"role": "assistant", "content": "latest"}]
    normalized = normalize_conversation_history(history)
    assert len(normalized) == 10
    assert normalized[0] == {"role": "user", "content": "old-3"}
    assert normalized[-1] == {"role": "assistant", "content": "latest"}


class FakeCompletions:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return next(self.responses)


def model_response(content="answer", tool_calls=None, finish_reason="stop"):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


def field(message, name):
    return message.get(name) if isinstance(message, dict) else getattr(message, name, None)


def make_client(responses):
    completions = FakeCompletions(responses)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


def test_follow_up_history_order_and_ambiguous_question_without_sql(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client, completions = make_client([model_response("Which building and date range do you mean?")])
    result = run_loop("Show me the consumption.", client=client, conversation_history=[
        {"role": "user", "content": "Which building used the most?"},
        {"role": "assistant", "content": "Main Academic Block."},
    ])
    sent_messages = completions.requests[0]["messages"]
    assert [field(message, "role") for message in sent_messages[:4]] == [
        "system", "user", "assistant", "user"
    ]
    assert field(sent_messages[2], "content") == "Main Academic Block."
    assert "clarification" in field(sent_messages[0], "content")
    assert result["tool_calls"] == []


def test_history_message_size_is_capped():
    normalized = normalize_conversation_history([{"role": "user", "content": "x" * 3000}])
    assert len(normalized[0]["content"]) == 2000


def test_api_failures_are_classified_without_exposing_details(monkeypatch):
    from openai import APIError

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class RateLimitError(APIError):
        status_code = 429

    class BrokenCompletions:
        def create(self, **kwargs):
            raise RateLimitError("secret detail", request=None, body=None)

    client = SimpleNamespace(chat=SimpleNamespace(completions=BrokenCompletions()))
    result = run_loop("question", client=client)
    assert result["error"] == "rate_limited"
    assert "secret detail" not in result["error"]


def test_max_turn_limit_is_reported(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="get_schema", arguments="{}"),
    )
    client, _ = make_client([model_response(tool_calls=[tool_call])])
    result = run_loop("question", client=client, max_turns=1)
    assert result["error"] == "max_turns_reached"


def test_tool_call_loop_reaches_answer_and_keeps_trace(database, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="run_sql", arguments='{"query":"SELECT COUNT(*) FROM readings"}'),
    )
    tool_response = model_response(content=None, tool_calls=[tool_call], finish_reason="tool_calls")
    client, completions = make_client([tool_response, model_response("There are 60 readings.")])
    result = run_loop("How many readings?", client=client)
    assert result["answer"] == "There are 60 readings."
    assert result["error"] is None
    assert result["tool_calls"][0]["name"] == "run_sql"
    assert "Rows: [(60,)]" in result["tool_calls"][0]["result"]
    last_message = completions.requests[1]["messages"][-2]
    assert field(last_message, "role") == "tool"


def test_model_receives_safe_sql_error_and_can_correct_query(database, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    invalid_call = SimpleNamespace(
        id="call-invalid",
        function=SimpleNamespace(
            name="run_sql",
            arguments='{"query":"SELECT * FROM missing_table"}',
        ),
    )
    corrected_call = SimpleNamespace(
        id="call-corrected",
        function=SimpleNamespace(
            name="run_sql",
            arguments='{"query":"SELECT COUNT(*) FROM readings"}',
        ),
    )
    client, completions = make_client([
        model_response(content=None, tool_calls=[invalid_call], finish_reason="tool_calls"),
        model_response(content=None, tool_calls=[corrected_call], finish_reason="tool_calls"),
        model_response("There are 60 readings."),
    ])

    result = run_loop("How many readings?", client=client)

    assert result["answer"] == "There are 60 readings."
    assert result["tool_calls"][0]["result"] == "Error: no such table referenced in query"
    first_tool_result = next(
        message
        for message in completions.requests[1]["messages"]
        if field(message, "role") == "tool"
    )
    assert field(first_tool_result, "role") == "tool"
    assert field(first_tool_result, "content") == "Error: no such table referenced in query"
    assert "Rows: [(60,)]" in result["tool_calls"][1]["result"]


def test_invalid_tool_arguments_are_recorded_and_handled(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="run_sql", arguments="[]"),
    )
    client, _ = make_client([
        model_response(content=None, tool_calls=[tool_call], finish_reason="tool_calls"),
        model_response("I could not run that query."),
    ])
    result = run_loop("question", client=client)
    assert result["error"] is None
    assert "invalid arguments" in result["tool_calls"][0]["result"]


def test_invalid_model_response_is_handled(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions([SimpleNamespace(choices=[])]))
    )
    assert run_loop("question", client=client)["error"] == "invalid_model_response"


def test_numeric_expected_answers_must_match():
    question = {"expected_all": [], "expected_any": [], "expected_numbers": [19.98]}
    assert not score_answer(question, "The answer is about 20 kWh.")["passed"]
    assert score_answer(question, "The average was 19.98 kWh.")["passed"]


def test_numeric_scoring_accepts_integer_and_decimal_forms_in_expected_order():
    question = {"expected_all": [], "expected_any": [], "expected_numbers": [30.0, 12.0]}
    assert score_answer(question, "30 and 12")["passed"]
    assert score_answer(question, "30.0, then 12.0")["passed"]
    assert not score_answer(question, "12.0, then 30.0")["passed"]


def test_accuracy_calculation_excludes_manual_review_and_errors():
    stats = run_evals._accuracy_stats([
        {"status": "passed"},
        {"status": "passed"},
        {"status": "failed"},
        {"status": "needs_review"},
        {"status": "api_error"},
    ])
    assert stats == {"passed": 2, "failed": 1, "scored": 3, "accuracy_percent": pytest.approx(66.6667)}


def test_zero_scored_questions_have_no_accuracy():
    stats = run_evals._accuracy_stats([
        {"status": "needs_review"},
        {"status": "api_error"},
    ])
    assert stats == {"passed": 0, "failed": 0, "scored": 0, "accuracy_percent": None}


def test_report_separates_splits_groups_manual_errors_and_partial(capsys):
    results = [
        {"status": "passed", "split": "dev", "group": "lookup", "error": None, "turns": 1},
        {"status": "failed", "split": "dev", "group": "lookup", "error": None, "turns": 2},
        {"status": "passed", "split": "test", "group": "join", "error": None, "turns": 3},
        {"status": "needs_review", "split": "test", "group": "ambiguous", "error": None, "turns": 1},
        {"status": "api_error", "split": "test", "group": "lookup", "error": "rate_limited", "turns": 1},
    ]
    run_evals._print_summary(results, selected_count=7, partial=True)
    report = capsys.readouterr().out
    assert "Run status: PARTIAL (5/7 selected questions processed)" in report
    assert "Overall automated accuracy: 2/3 (66.7%; n=3; 1 failed)" in report
    assert "dev automated accuracy: 1/2 (50.0%; n=2; 1 failed)" in report
    assert "test automated accuracy: 1/1 (100.0%; n=1; 0 failed)" in report
    assert "Manual-review-only questions: 1" in report
    assert "API/agent errors: 1" in report
    assert "Interrupted / unattempted questions: 2" in report
    assert "lookup: 1/2" in report


def test_run_evals_appends_timestamped_records_and_summarizes_current_run_only(
    tmp_path,
    monkeypatch,
    capsys,
):
    output_path = tmp_path / "explicit-run.jsonl"
    questions = [{"id": 1, "question": "Question", "group": "lookup", "split": "dev"}]
    responses = iter([
        {"answer": "answer one", "error": None, "tool_calls": [{"name": "run_sql"}], "turns": 1},
        {"answer": "answer two", "error": None, "tool_calls": [], "turns": 2},
    ])
    monkeypatch.setattr(run_evals, "run_loop", lambda *args, **kwargs: next(responses))

    run_evals.run_evals(questions, model="test-model", output_path=output_path)
    first_report = capsys.readouterr().out
    run_evals.run_evals(questions, model="test-model", output_path=output_path)
    second_report = capsys.readouterr().out

    records = [json.loads(line) for line in output_path.read_text().splitlines()]
    assert len(records) == 2
    assert records[0]["model"] == "test-model"
    assert records[0]["timestamp"].endswith("+00:00")
    assert records[0]["tool_calls"] == [{"name": "run_sql"}]
    assert first_report.count("Overall automated accuracy: 1/1") == 1
    assert second_report.count("Overall automated accuracy: 1/1") == 1


def test_evaluation_stops_after_connection_failure(tmp_path, monkeypatch):
    calls = []

    def failed_run(question, model, **kwargs):
        calls.append(question)
        return {"answer": "", "error": "api_connection_error", "tool_calls": [], "turns": 1}

    monkeypatch.setattr(run_evals, "run_loop", failed_run)
    results = run_evals.run_evals(
        [
            {"id": 1, "question": "first", "group": "test"},
            {"id": 2, "question": "second", "group": "test"},
        ],
        output_path=tmp_path / "results.jsonl",
    )
    assert calls == ["first"]
    assert len(results) == 1
    assert results[0]["status"] == "api_error"


@pytest.mark.parametrize("error", ["invalid_model_response", "unexpected_agent_failure"])
def test_evaluation_stops_after_any_api_error_and_preserves_record(
    tmp_path, monkeypatch, capsys, error
):
    calls = []
    output_path = tmp_path / "results.jsonl"

    def failed_run(question, model, **kwargs):
        calls.append(question)
        return {"answer": "", "error": error, "tool_calls": [], "turns": 1}

    monkeypatch.setattr(run_evals, "run_loop", failed_run)
    results = run_evals.run_evals(
        [
            {"id": 1, "question": "first"},
            {"id": 2, "question": "second"},
        ],
        output_path=output_path,
    )

    output = capsys.readouterr().out
    records = [json.loads(line) for line in output_path.read_text().splitlines()]
    assert calls == ["first"]
    assert len(results) == len(records) == 1
    assert records[0]["status"] == "api_error"
    assert records[0]["error"] == error
    assert "Stopping evaluation after API/agent error" in output
    assert "Run status: FAILED (1/2 selected questions processed)" in output
    assert "Interrupted / unattempted questions: 1" in output


def test_integrity_failure_preserves_current_record_and_stops_without_database_write(
    tmp_path, monkeypatch, capsys
):
    calls = []
    output_path = tmp_path / "results.jsonl"

    def successful_run(question, model, **kwargs):
        calls.append(question)
        return {"answer": "ok", "error": None, "tool_calls": [], "turns": 1}

    monkeypatch.setattr(run_evals, "run_loop", successful_run)
    monkeypatch.setattr(run_evals, "score_answer", lambda *_: {"passed": True})
    monkeypatch.setattr(run_evals, "_readings_count", lambda: 7)
    questions = [
        {"id": 21, "question": "integrity question"},
        {"id": 22, "question": "must not run"},
    ]

    results = run_evals.run_evals(questions, output_path=output_path)

    output = capsys.readouterr().out
    records = [json.loads(line) for line in output_path.read_text().splitlines()]
    assert calls == ["integrity question"]
    assert len(results) == len(records) == 1
    assert records[0]["id"] == 21
    assert records[0]["status"] == "passed"
    assert "INTEGRITY CHECK FAILED" in output
    assert "expected 11520, found 7" in output
    assert "Run status: FAILED (1/2 selected questions processed)" in output
    assert "Interrupted / unattempted questions: 1" in output
