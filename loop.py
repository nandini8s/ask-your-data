import json
import logging
import os
import time

from dotenv import load_dotenv

from tools import get_schema, run_sql
load_dotenv()

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
MAX_TURNS = 8
MAX_HISTORY_MESSAGES = 10
MAX_HISTORY_MESSAGE_CHARS = 2000
logger = logging.getLogger(__name__)
SYSTEM_PROMPT = (
    "The campus database is SQLite. Call get_schema before writing SQL to inspect "
    "the tables and columns. Use only SELECT queries with run_sql; the database "
    "tool is read-only. The reading_time column is text, so extract its hour with "
    "substr(reading_time, 12, 2). Join readings with buildings to show building "
    "names. If a table or column does not exist, say so and do not guess. Explain "
    "results simply and do not claim data that a tool did not return. Write dates "
    "as YYYY-MM-DD. If the user asks an ambiguous question or omits information "
    "needed to answer it (such as which building, date range, metric, or comparison), "
    "ask one concise clarification question before calling any database tool. Use "
    "conversation history to resolve follow-up references when it supplies the "
    "missing context; do not ask again when the context is sufficient. If a user "
    "asks a general question that does not require campus data, answer directly "
    "without calling a database tool."
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
        if not isinstance(args, dict) or set(args) != {"query"}:
            return "Error: invalid arguments for run_sql"
        if not isinstance(args["query"], str) or not args["query"].strip():
            return "Error: query must be a non-empty SQL string"
        return run_sql(args["query"])
    if name == "get_schema":
        if not isinstance(args, dict) or args:
            return "Error: invalid arguments for get_schema"
        return get_schema()
    return "Error: unknown tool"


def _create_completion(client, **kwargs):
    from openai import APIStatusError, APITimeoutError

    timeout_retries = 0
    status_retries = 0
    while True:
        try:
            return client.chat.completions.create(**kwargs)
        except APITimeoutError:
            if timeout_retries == 1:
                raise
            timeout_retries += 1
        except APIStatusError as error:
            if error.status_code != 503 or status_retries == 3:
                raise
            status_retries += 1
            time.sleep(2)


def normalize_conversation_history(conversation_history):
    recent_history = []
    if conversation_history:
        for message in conversation_history:
            if isinstance(message, dict) and message.get("role") in ("user", "assistant"):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    recent_history.append({
                        "role": message["role"],
                        "content": content.strip()[:MAX_HISTORY_MESSAGE_CHARS],
                    })
    return recent_history[-MAX_HISTORY_MESSAGES:]


def run_loop(
    question,
    client=None,
    model=MODEL,
    max_turns=MAX_TURNS,
    conversation_history=None,
):
    """Ask the model a question, executing its database tool calls as needed."""
    print("model:", model)
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
            timeout=60.0,
            max_retries=0,
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]
    messages.extend(normalize_conversation_history(conversation_history))
    messages.append({"role": "user", "content": question})

    tool_trace = []
    for turn in range(1, max_turns + 1):
        print(f"[turn {turn}] calling model...")
        try:
            response = _create_completion(
                client,
                model=model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
            )
        except APIError as error:
            status_code = getattr(error, "status_code", None)
            if status_code == 429:
                error_code = "rate_limited"
            elif status_code == 408:
                error_code = "api_timeout"
            elif error.__class__.__name__ == "APITimeoutError":
                error_code = "api_timeout"
            elif error.__class__.__name__ == "APIConnectionError":
                error_code = "api_connection_error"
            else:
                error_code = "api_error"
            logger.warning("Model request failed (%s; status=%s)", error_code, status_code)
            return {
                "answer": "",
                "error": error_code,
                "tool_calls": tool_trace,
                "turns": turn,
            }
        except Exception as error:
            logger.exception(
                "Unexpected failure while requesting a model response (%s)",
                type(error).__name__,
            )
            return {"answer": "", "error": "api_error", "tool_calls": tool_trace, "turns": turn}
        try:
            choice = response.choices[0]
            message = choice.message
            finish_reason = choice.finish_reason
        except (AttributeError, IndexError, TypeError):
            logger.warning("Model returned an invalid response structure")
            return {"answer": "", "error": "invalid_model_response", "tool_calls": tool_trace, "turns": turn}
        tool_calls = getattr(message, "tool_calls", None)
        content = getattr(message, "content", None)
        if (
            finish_reason is None
            or (content is not None and not isinstance(content, str))
            or (tool_calls is not None and not isinstance(tool_calls, (list, tuple)))
        ):
            logger.warning("Model returned an invalid response structure")
            return {"answer": "", "error": "invalid_model_response", "tool_calls": tool_trace, "turns": turn}
        messages.append(message)

        if not tool_calls:
            if finish_reason != "stop":
                logger.warning("Model response ended before a final answer (%s)", finish_reason)
                return {
                    "answer": "The model response was incomplete. Please try again.",
                    "error": "invalid_model_response",
                    "tool_calls": tool_trace,
                    "turns": turn,
                }
            answer = content or "Model stopped without a text answer."
            return {
                "answer": answer,
                "error": None,
                "tool_calls": tool_trace,
                "turns": turn,
            }

        for tool_call in tool_calls:
            try:
                name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments or "{}")
                if not isinstance(arguments, dict):
                    raise TypeError("arguments must be a JSON object")
                result = execute_tool(name, arguments)
            except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as error:
                name = getattr(getattr(tool_call, "function", None), "name", "unknown")
                arguments = getattr(getattr(tool_call, "function", None), "arguments", "")
                logger.info("Invalid arguments for tool %s: %s", name, type(error).__name__)
                result = f"Error: invalid arguments for {name}"
            except Exception as error:
                name = getattr(getattr(tool_call, "function", None), "name", "unknown")
                arguments = getattr(getattr(tool_call, "function", None), "arguments", "")
                logger.exception("Database tool %s failed (%s)", name, type(error).__name__)
                result = f"Error: {name} could not complete the request"
            result = str(result)
            tool_trace.append(
                {
                    "name": name,
                    "arguments": arguments,
                    "result": result,
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": getattr(tool_call, "id", ""),
                    "content": result,
                }
            )

    return {
        "answer": "I couldn't complete the answer within the tool-call limit.",
        "error": "max_turns_reached",
        "tool_calls": tool_trace,
        "turns": max_turns,
    }


if __name__ == "__main__":
    try:
        question = input("Ask a question about the campus database: ")
        print(json.dumps(run_loop(question), indent=2))
    except KeyboardInterrupt:
        raise SystemExit("Cancelled.")
