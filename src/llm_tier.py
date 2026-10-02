"""Tier 3: ask a model. Costs money, ~200ms, always answers.

Reached only when regex and ML both decline, so this tier sees the lines that
are genuinely ambiguous -- which is why it can be paid for at all.
"""
import os

from . import models


def available() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


def classify(line: str, model_id: str = None):
    """Return (category, note) or (None, reason) when the tier cannot be used."""
    try:
        model_id = models.resolve(model_id)
    except models.UnknownModel as e:
        return None, str(e)

    if not available():
        return None, "no GROQ_API_KEY"

    prompt = (
        "Classify this application log line into exactly one category:\n"
        "Security Alert, Resource Usage, Deprecation Warning, Workflow Error, Unknown\n\n"
        "Rules: decide before considering Unknown. A line reporting a failure, a "
        "threshold, or a scheduled change belongs in one of the four real "
        "categories. Choose Unknown only for lines describing nothing wrong and "
        "nothing scheduled.\n\n"
        f"Line: {line}\n\n"
        "Reply with the category name only."
    )

    try:
        from groq import Groq
        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        resp = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        msg = resp.choices[0].message
        raw = (msg.content or "").strip()
        usage = getattr(resp, "usage", None)
        cost = models.estimate_cost_usd(
            model_id,
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )
        return raw, cost
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"[:160]
