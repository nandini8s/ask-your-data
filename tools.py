import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "campus.db"


def get_schema():
    conn = None
    try:
        conn = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
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
    query = query.strip()
    normalized_query = query.lower()
    if not normalized_query.startswith("select"):
        return "Error: only SELECT queries are allowed"
    if ";" in query[:-1]:
        return "Error: only one SELECT query is allowed"

    conn = None
    try:
        conn = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute(query)
        columns = [description[0] for description in cur.description]
        rows = cur.fetchmany(50)
        result = f"Columns: {', '.join(columns)}\nRows: {rows!r}"
        if cur.fetchone() is not None:
            result += "\n(Showing first 50 rows; more exist. Use aggregation or LIMIT.)"
        return result
    except sqlite3.Error as error:
        return f"Error: {error}"
    finally:
        if conn is not None:
            conn.close()
