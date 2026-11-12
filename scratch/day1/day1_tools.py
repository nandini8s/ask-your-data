import os
import json
import time
import openai
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ================= SETTINGS (the only part you edit) =================
MODEL = "gemini-3.8-flash"
QUESTION = "How many rows are in the zebra table?"
USE_SCHEMA_TOOL = True

RUN_SQL_DESCRIPTION = "Runs a read-only SQL SELECT query on a SQLite database and returns the rows. Use this whenever the question needs data from the database."
GET_SCHEMA_DESCRIPTION = "Returns the table names and column names of the database. Use this before writing any SQL if you are not sure which tables or columns exist."
# =====================================================================

client = OpenAI(
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    api_key=os.environ["GEMINI_API_KEY"],
)

run_sql_tool = {
    "type": "function",
    "function": {
        "name": "run_sql",
        "description": RUN_SQL_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "A single SQLite SELECT statement."}
            },
            "required": ["query"],
        },
    },
}

get_schema_tool = {
    "type": "function",
    "function": {
        "name": "get_schema",
        "description": GET_SCHEMA_DESCRIPTION,
        "parameters": {"type": "object", "properties": {}},
    },
}

tools = [run_sql_tool]
if USE_SCHEMA_TOOL:
    tools.append(get_schema_tool)

print("model:", MODEL)
print("question:", QUESTION)
print("tools available:", [t["function"]["name"] for t in tools])

response = None
for attempt in range(4):
    try:
        response = client.chat.completions.create(
            model=MODEL,
            tools=tools,
            messages=[{"role": "user", "content": QUESTION}],
        )
        break
    except openai.InternalServerError:
        print(f"Server busy (attempt {attempt + 1} of 4). Waiting 15 seconds...")
        time.sleep(15)

if response is None:
    raise SystemExit("Server still busy. Try again in 10 minutes.")

choice = response.choices[0]
print("finish_reason:", choice.finish_reason)
print("content:", choice.message.content)

if choice.message.tool_calls:
    for call in choice.message.tool_calls:
        args = json.loads(call.function.arguments)
        print("tool:", call.function.name, "| arguments:", args)
else:
    print("no tool was called")