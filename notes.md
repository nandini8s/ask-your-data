Baseline (5 runs, no changes): 4 of 5 runs listed the tables with sqlite_master. 1 of 5 wrote SELECT count(*) FROM sqlite_master, which counts tables and not customers. The model's output varies between identical runs, and it can write a query that looks reasonable but answers the wrong question. Without schema information it can't know there's a customers table.


Exp 1 and 1b: With the main description vague ("database tool") but the query field still saying "SQLite", 3 of 3 runs used SQLite syntax. When I made both texts vague, 2 of 2 runs switched to PostgreSQL syntax (information_schema), the same guess the model made before I mentioned SQLite at all. The model uses every piece of text in the tool definition, and when none says which database it is, it guesses.


Exp 2: Asked "What is 2+2?" with run_sql available. In 3 of 3 runs finish_reason was stop, content held the answer, and no tool was called. The model decides whether a tool is needed, so tools are never forced.


Exp 3: Asked "How many rows are in the zebra table?" with only run_sql available (model: gemini-3.8-flash). In 3 of 3 runs the model wrote SELECT COUNT(*) FROM zebra immediately, without checking that the table exists. It trusts what the question says and guesses when it can't see the database.


Exp 4: Asked "How many customers are in the database?" with run_sql and get_schema both available. In 3 of 3 runs the model called get_schema first, with empty arguments, instead of guessing a table name. Earlier, when the get_schema description was still a TODO placeholder and the query field was described wrongly, this was inconsistent. Once both descriptions were real, the behavior became reliable. This suggests description quality matters, but I changed two things at once, so I can't prove which one caused it.


Exp 5: Asked about the zebra table again, now with get_schema available. In 2 of 2 runs the model called get_schema first. Compared with Exp 3 (same question, 3 of 3 guessed), adding one tool changed the behavior. Note: this question was worded "in zebra table" without "the", and the sample is small.


Exp 6 (skipped): get_schema was already called first every time, so a stronger description had nothing left to improve (ceiling effect).

Important: in all experiments the model only asked for a tool. Nothing ran and no schema was returned. That comes in Day 2.

Bugs I hit and fixed:
- Used QUESTION as the description of the query field, so the model saw my question twice instead of a description of the field.
- KeyError: 'query' when get_schema was called, because it takes no inputs. Each tool needs its own handling.
- SyntaxError from a model name without quotes.
- KeyError: 'GEMINI_MODEL' because the variable was missing from .env.
- 503 (Google's server busy): retry with a short wait.
- 429 (free quota of 20 requests per day per model): wait for the reset or switch to a model with a higher limit.

Main takeaways:
1. A tool call is a request. The model never runs anything; my code does.
2. The model decides whether to use a tool (Exp 2), and which one.
3. It uses all the text in the tool definition (name, descriptions, parameter descriptions). When something is missing, it guesses (PostgreSQL syntax, the zebra table).
4. Identical runs can give different results, and a wrong query can look reasonable, so I need evals and a schema tool.
5. Tool descriptions are part of the program: changing one sentence changed behavior.

## Day 2 ground truth (campus.db, verified with sqlite3)
- Highest average night use (hours 0-4): CS Lab Block, 20.0 kWh
- Highest total use: Main Academic Block, 35,371 kWh (CS Lab Block second, 32,937)
- Highest-consumption day: 2026-09-24 (3,237 kWh), then 2026-09-25 (3,224)
- Library avg kWh, hours 0-2: exam week 27.9 vs other days 3.0
- Row counts: 8 buildings, 11,520 readings, 2 events