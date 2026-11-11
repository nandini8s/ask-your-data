import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "campus.db"
MAX_RESULT_ROWS = 50
QUERY_TIMEOUT_SECONDS = 2.0


def _read_only_authorizer(action, arg1, arg2, database_name, trigger_name):
    allowed_actions = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
        getattr(sqlite3, "SQLITE_RECURSIVE", -1),
    }
    if action not in allowed_actions:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION:
        function_name = (arg2 or arg1 or "").lower()
        if function_name in {"load_extension", "writefile", "readfile"}:
            return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _connect_read_only(enforce_select_only=False):
    connection = sqlite3.connect(f"{DB_PATH.resolve().as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    if enforce_select_only:
        connection.set_authorizer(_read_only_authorizer)
        deadline = time.monotonic() + QUERY_TIMEOUT_SECONDS
        connection.set_progress_handler(
            lambda: 1 if time.monotonic() >= deadline else 0,
            1000,
        )
    return connection


def _first_sql_keyword(query):
    """Read the first token while ignoring SQL comments and whitespace."""
    index = 0
    length = len(query)
    while index < length:
        if query[index].isspace():
            index += 1
        elif query.startswith("--", index):
            newline = query.find("\n", index + 2)
            index = length if newline == -1 else newline + 1
        elif query.startswith("/*", index):
            end = query.find("*/", index + 2)
            if end == -1:
                return ""
            index = end + 2
        else:
            end = index
            while end < length and (query[end].isalpha() or query[end] == "_"):
                end += 1
            return query[index:end].upper()
    return ""


def get_schema():
    conn = None
    try:
        conn = _connect_read_only()
        cur = conn.cursor()
        tables = cur.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        description = []
        for (table_name,) in tables:
            quoted_name = '"' + table_name.replace('"', '""') + '"'
            columns = cur.execute(f"PRAGMA table_info({quoted_name})").fetchall()
            column_descriptions = [
                f"{column[1]} ({column[2] or 'type unspecified'}"
                f"{', primary key' if column[5] else ''})"
                for column in columns
            ]
            samples = cur.execute(f"SELECT * FROM {quoted_name} LIMIT 3").fetchall()
            sample_text = ", ".join(repr(row) for row in samples) or "(no rows)"
            description.append(
                f"Table {table_name}:\n"
                f"  columns: {', '.join(column_descriptions)}\n"
                f"  sample rows: {sample_text}"
            )
        return "\n\n".join(description)
    finally:
        if conn is not None:
            conn.close()


def run_sql(query):
    if not isinstance(query, str):
        return "Error: query must be a SQL string"
    query = query.strip()
    if _first_sql_keyword(query) not in {"SELECT", "WITH"}:
        return "Error: only SELECT queries are allowed"

    conn = None
    try:
        conn = _connect_read_only(enforce_select_only=True)
        cur = conn.cursor()
        cur.execute(query)
        if cur.description is None:
            return "Error: only SELECT queries are allowed"
        columns = [description[0] for description in cur.description]
        rows = cur.fetchmany(MAX_RESULT_ROWS)
        result = f"Columns: {', '.join(columns)}\nRows: {rows!r}"
        if cur.fetchone() is not None:
            result += "\n(Showing first 50 rows; more exist. Use aggregation or LIMIT.)"
        return result
    except sqlite3.ProgrammingError as error:
        if "one statement" in str(error).lower():
            return "Error: only one SELECT query is allowed"
        return "Error: query could not be completed"
    except sqlite3.OperationalError as error:
        if "interrupted" in str(error).lower():
            return "Error: query exceeded the time limit"
        if "not authorized" in str(error).lower():
            return "Error: only read-only SELECT queries are allowed"
        return "Error: query could not be completed"
    except sqlite3.Error:
        return "Error: query could not be completed"
    finally:
        if conn is not None:
            conn.close()
