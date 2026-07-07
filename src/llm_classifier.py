import os
from dotenv import load_dotenv
from groq import Groq

from src.config import CATEGORIES

load_dotenv()

_GROQ_PROMPT = f"""
You are a log classifier. Classify the given log line into exactly one of these categories:

- Security Alert: e.g. "Multiple failed login attempts detected for user admin_42"
- Resource Usage: e.g. "Memory usage at 87% on server node-12"
- Workflow Error: e.g. "Task queue processing failed for job ID 8823"
- Deprecation Warning: e.g. "Function getUserData() is deprecated"
- Unknown: e.g. "User jdoe logged in from Chrome on Windows 10"

Respond with ONLY the category name. No explanation, no punctuation.
"""


def classify_llm(text: str) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY not found in .env file")

    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": _GROQ_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0,
        max_tokens=20,
    )

    result = response.choices[0].message.content.strip()
    for cat in CATEGORIES:
        if result.lower() == cat.lower():
            return cat
    return "Unknown"


if __name__ == "__main__":
    test_lines = [
        "Port scan detected from external IP 45.33.32.156",
        "Cache hit ratio dropped to 34% on Redis instance",
        "User updated profile picture successfully",
    ]
    for line in test_lines:
        print(f"{classify_llm(line):25s} | {line}")
