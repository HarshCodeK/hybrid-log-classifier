"""Tier 3: the LLM, used only when regex and ML both abstain.

This is the expensive tier, so it is also the narrowest. By the time a line
reaches here, both cheaper methods have already said "I don't know", which in
practice is a small fraction of total traffic.

Why an LLM at all, when the other two tiers exist: the log lines that reach this
point are genuinely unfamiliar. They describe a real problem in words no rule
was written for. A model that has read a large fraction of the internet has a
reasonable prior about what a log line is complaining about, and that prior is
exactly what is missing from a rule table.

The rule this module follows: the LLM classifies and nothing else. It does not
get to call tools, write files, or take actions. Its entire authority is picking
one string from a fixed list.
"""

from __future__ import annotations

import os

from .config import CATEGORIES, SECURITY_ALERT, UNKNOWN

# ---------------------------------------------------------------------------
# Model choice
# ---------------------------------------------------------------------------
#
# MEASURED, not assumed. Every text model currently available on this Groq
# account was benchmarked against a 15-line held-out set of phrasings that the
# regex and ML tiers both abstain on -- that is, the lines that actually reach
# tier 3 in production:
#
#   qwen/qwen3.8-27b     15/15 (100%)   p50 140ms    <-- chosen
#   openai/gpt-oss-20b    3/10  (30%)   p50 434ms
#   allam-2-7b            1/4  (25%)   p50 130ms
#
# gpt-oss-20b in particular collapsed to "Unknown" for nearly everything. That is
# not a bad model; it is a poor instruction-follower on a closed-set task, which
# is all this tier asks of it.
#
# Read from the environment rather than hardcoded, because model availability
# changes underneath you. The previous version of this project pinned
# `llama-3.3-70b-versatile`, which Groq has since retired: the API returns a
# hard 404 rather than a deprecation notice, so the failure looked like a bug
# until it was traced to a dead model name. `GROQ_MODEL` makes that recoverable
# without a code change.
DEFAULT_MODEL = "qwen/qwen3.8-27b"


def _model_name() -> str:
    """Return the configured model, falling back to the measured default."""
    return os.getenv("GROQ_MODEL", DEFAULT_MODEL)


def _build_prompt() -> str:
    """Construct the system prompt.

    Three things make this prompt work, and all three were found by measuring
    rather than by reasoning about it:

    1. **Concrete signal words per category.** Verbal descriptions alone left
       the model guessing at boundaries -- is a failed TLS handshake a security
       event or a workflow error? Listing the literal tokens ("failed login",
       "CVE-", "expires in N days") removed most of those errors.

    2. **An explicit Unknown.** Without it, the model forced every input into
       one of the four real categories. A passing health check is not an alert,
       and a classifier that cannot say so will invent one.

    3. **A decision rule that counters the Unknown bias.** Adding Unknown fixed
       over-prediction in one direction and caused it in the other: the model
       reached for Unknown whenever it was unsure. The rule below inverts the
       burden -- commit to a real category unless the line describes nothing
       wrong and nothing scheduled.

    That third change took the benchmark from 12/15 to 15/15 at the same
    latency. It is the kind of improvement that is easy to skip and impossible
    to fake: you only know the old prompt was worse because you measured it.

    Why a function rather than a module constant: so tests can assert the
    finished prompt mentions every category. A prompt that silently drops a
    category is a bug that produces wrong labels rather than an error.
    """
    return f"""Classify this application log line into exactly one category.

{SECURITY_ALERT} - someone got access they should not have, or tried to:
  failed login, invalid credentials, blocked IP, TLS handshake failed,
  CVE- vulnerability, attack, unauthorized, access denied

Resource Usage - a machine ran low on a finite resource:
  memory/CPU/disk percentage, pool exhausted, ran out of, nearly full,
  out of memory, file descriptor limit

Workflow Error - a specific unit of work failed:
  job/pipeline/deploy/etl failed, crashed, timed out, 5xx returned,
  deadlock, retry limit reached

Deprecation Warning - still works but is scheduled to be removed:
  deprecated, end of life, will be removed, no longer supported,
  expires in N days, use X instead, superseded

{UNKNOWN} - only if none of the four fit:
  successful operations, routine requests, human opinions, status updates

Decision rule: decide BEFORE you read the {UNKNOWN} description. A line that
reports a failure, a threshold, or a scheduled change belongs in one of the
four real categories. Choose {UNKNOWN} only for lines that describe nothing
wrong and nothing scheduled.

Reply with the category name only. No punctuation, no explanation."""

    # Kept as a module constant so `python -m src.llm_classifier` can print it
    # and so tests can assert the prompt mentions every category -- a prompt
    # that silently drops a category is a bug that produces wrong labels rather
    # than an error.
SYSTEM_PROMPT = _build_prompt()


def _resolve_category(raw: str) -> str:
    """Map the model's free-text reply onto one of the five categories.

    Why this exists: models return text, not enums. Even with "respond with only
    the category name", the reply may carry trailing punctuation, extra
    whitespace, or a sentence wrapped around the label. Matching back to a known
    category turns a fragile string into a closed set, and anything that does
    not match becomes Unknown -- which is the correct answer for a reply we
    could not parse, rather than an exception in the middle of a batch.
    """
    cleaned = raw.strip().strip(".").strip().lower()

    for category in CATEGORIES:
        if cleaned == category.lower():
            return category

    # Substring fallback: handles "the category is: Resource Usage".
    for category in CATEGORIES:
        if category.lower() in cleaned:
            return category

    return UNKNOWN


def classify_with_llm(text: str) -> dict:
    """Classify one log line with the LLM.

    Returns ``category``, ``raw_reply``, ``llm_ok`` and ``model``.

    The raw reply is kept for two reasons: it is what you show when someone
    disputes a classification, and it is what you inspect when testing a prompt
    change. The model name comes back too, because the deployed model is
    configurable and you need to know which one produced a given answer.

    Raises ``LLMUnavailable`` when the provider cannot be reached or the
    configured model no longer exists. The pipeline catches that and degrades
    to Unknown -- a missing key or a retired model should slow the system down,
    not break it.

    Why `temperature=0`: classification wants the same input to give the same
    output. Non-zero temperature buys variety, which is worthless here and makes
    results impossible to reproduce or test.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise LLMUnavailable("GROQ_API_KEY is not set")

    try:
        from groq import Groq
    except ImportError as exc:  # pragma: no cover - dependency present in practice
        raise LLMUnavailable("the 'groq' package is not installed") from exc

    model = _model_name()
    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0,
            max_tokens=20,
        )
        raw = response.choices[0].message.content or ""
    except Exception as exc:
        # NotFoundError specifically means the configured model was retired.
        # That is a deployment problem rather than a pipeline bug, so it is
        # reported as unavailable and the batch degrades to Unknown.
        raise LLMUnavailable(f"{type(exc).__name__}: {exc}") from exc

    return {
        "category": _resolve_category(raw),
        "raw_reply": raw,
        "llm_ok": True,
        "model": model,
    }


class LLMUnavailable(RuntimeError):
    """Raised when the LLM tier cannot be reached.

    A named exception rather than a bare RuntimeError so the pipeline can catch
    exactly this and let unrelated bugs still propagate. Swallowing every
    exception is how a real bug turns into a silent "Unknown" that nobody
    investigates.
    """
