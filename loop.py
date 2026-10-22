import json
import os
import time

from dotenv import load_dotenv

from tools import get_schema, run_sql


MODEL = "gemini-3.8-flash"
MAX_TURNS = 8
SYSTEM_PROMPT = (
    "The campus database is SQLite. Call get_schema before writing SQL to inspect "
    "the tables and columns. Use only SELECT queries with run_sql; the database "
    "tool is read-only. The reading_time column is text, so extract its hour with "
    "substr(reading_time, 12, 2). Join readings with buildings to show building "
    "names. If a table or column does not exist, say so and do not guess. Explain "
    "results simply and do not claim data that a tool did not return."
)

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": (
                "Runs one read-only SQLite SELECT query and returns column names "
                "and up to 50 rows."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A single SQLite SELECT statement.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_schema",
            "description": (
                "Returns the database tables, columns, and sample rows. "
                "Use this to inspect the schema before writing SQL."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def execute_tool(name, args):
    if name == "run_sql":
        return run_sql(args["query"])
    if name == "get_schema":
        return get_schema()
    return "Error: unknown tool"


def _create_completion(client, **kwargs):
    from openai import InternalServerError

    for attempt in range(4):
        try:
            return client.chat.completions.create(**kwargs)
        except InternalServerError:
            if attempt == 3:
                raise
            time.sleep(2)


def run_loop(question, client=None, model=MODEL, max_turns=MAX_TURNS):
    """Ask the model a question, executing its database tool calls as needed."""
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("Set GEMINI_API_KEY in your environment or .env file.")

    from openai import APIError

    if client is None:
        from openai import OpenAI

        client = OpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=api_key,
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    tool_trace = []
    for turn in range(1, max_turns + 1):
        try:
            response = _create_completion(
                client,
                model=model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
            )
        except APIError as error:
            return {
                "answer": f"API error: {error}",
                "tool_calls": tool_trace,
                "turns": turn,
            }
        choice = response.choices[0]
        messages.append(choice.message)

        if not choice.message.tool_calls:
            if choice.finish_reason != "stop":
                answer = (
                    "Model finished without a final answer "
                    f"(finish_reason={choice.finish_reason!r})."
                )
            else:
                answer = choice.message.content or "Model stopped without a text answer."
            return {"answer": answer, "tool_calls": tool_trace, "turns": turn}

        for tool_call in choice.message.tool_calls:
            try:
                arguments = json.loads(tool_call.function.arguments or "{}")
                result = execute_tool(tool_call.function.name, arguments)
            except (json.JSONDecodeError, KeyError, TypeError) as error:
                arguments = tool_call.function.arguments
                result = f"Error: invalid arguments for {tool_call.function.name}: {error}"
            result = str(result)
            tool_trace.append(
                {
                    "name": tool_call.function.name,
                    "arguments": arguments,
                    "result": result,
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                }
            )

    return {
        "answer": "I couldn't complete the answer within the tool-call limit.",
        "tool_calls": tool_trace,
        "turns": max_turns,
    }


if __name__ == "__main__":
    try:
        question = input("Ask a question about the campus database: ")
        print(json.dumps(run_loop(question), indent=2))
    except KeyboardInterrupt:
        raise SystemExit("Cancelled.")
