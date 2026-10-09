import os
from dotenv import load_dotenv

load_dotenv()
key = os.environ.get("GEMINI_API_KEY")
print("Key found:", key is not None)
print("Starts with:", key[:4] if key else None)
