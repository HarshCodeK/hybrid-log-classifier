"""Tier 1: classify a log line with regular expressions.

Why this tier exists: most log lines are formulaic. "Memory usage at 92%" means
the same thing every single time, and no machine learning is required to notice
that. Handling those first costs microseconds and zero money.

This is the cheapest tier in both latency and cost, and in practice it resolves
the large majority of real log traffic. That is the entire argument for the
three-tier design.
"""

from __future__ import annotations

from .config import REGEX_PATTERNS, UNKNOWN


def classify_with_regex(text: str) -> tuple[str | None, str | None]:
    """Return ``(category, matched_pattern)`` or ``(None, None)`` on no match.

    Returning the pattern that fired is what makes a classification
    explainable. When someone asks "why did this line become a Security Alert",
    the answer is a specific rule rather than a confidence score, and that is a
    far more satisfying thing to show in a UI.

    Why the nested loop: `REGEX_PATTERNS` is ordered most-specific-first, so we
    return on the first category that matches anything. Within a category, any
    pattern matching is enough -- no need for the strongest match.
    """
    for category, patterns in REGEX_PATTERNS.items():
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return category, pattern.pattern
    return None, None


if __name__ == "__main__":
    # Quick manual check: python -m src.regex_classifier
    samples = [
        "Multiple failed login attempts detected for user admin_42",
        "Memory usage at 87% on server node-12, threshold exceeded",
        "Task queue processing failed for job ID 8823, retry limit reached",
        "Function getUserData() is deprecated, use fetchUser() instead",
        "Health check passed for service api-gateway",
    ]
    for line in samples:
        category, pattern = classify_with_regex(line)
        label = category or "no match (would fall to ML)"
        print(f"{label:22s} | {line}")
        if pattern:
            print(f"{'':22s}   matched: {pattern}")
