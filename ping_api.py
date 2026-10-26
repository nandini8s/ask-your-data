import os
import time

import openai
from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()
MODEL = "gemini-3.5-flash-lite"  # Change this line to test another model.

client = OpenAI(
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    api_key=os.environ["GEMINI_API_KEY"],
    timeout=20.0,
    max_retries=0,
)

start = time.time()
try:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Say hi"}],
    )
    print("OK in", round(time.time() - start, 1), "s:", response.choices[0].message.content)
except openai.APITimeoutError:
    print("TIMEOUT after", round(time.time() - start, 1), "s")
except openai.APIError as error:
    print("API error:", type(error).__name__, error)
