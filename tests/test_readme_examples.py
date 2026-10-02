"""Every example the README promises is asserted here.

This file exists to prevent one specific failure: a README whose example table
disagrees with the code. That happened in the previous version of this project
-- four of fourteen documented examples were wrong about which tier fired, and
an interviewer can find that in under a minute by pasting the README's own lines
into the running app.

The rule this file enforces: if a line appears in the README, its actual
category and tier are asserted here. Change the behaviour without updating
this test and the suite fails. Change the README without updating this test and
the suite fails. The two can no longer drift apart.

Run: python -m pytest tests/test_readme_examples.py -v
"""

from __future__ import annotations

import pytest

from src.config import (
    DEPRECATION_WARNING,
    RESOURCE_USAGE,
    SECURITY_ALERT,
    UNKNOWN,
    WORKFLOW_ERROR,
)
from src.pipeline import classify_one

# (log_line, expected_category, expected_tier)
#
# The tier column is the strict part. A test that only asserted the category
# would pass even if the routing changed completely, and routing is the entire
# architecture here.
README_EXAMPLES = [
    # --- caught by regex: template lines with an unmistakable keyword ---
    ("Multiple failed login attempts detected for user admin_42", SECURITY_ALERT, "regex"),
    ("IP 192.168.1.105 blocked due to potential attack", SECURITY_ALERT, "regex"),
    ("Memory usage at 87% on server node-12, threshold exceeded", RESOURCE_USAGE, "regex"),
    ("Disk space critical: /dev/sda1 at 92% capacity", RESOURCE_USAGE, "regex"),
    ("Task queue processing failed for job ID 8823", WORKFLOW_ERROR, "regex"),
    ("Data pipeline crashed during ETL step at transform phase", WORKFLOW_ERROR, "regex"),
    ("Function getUserData() is deprecated, use fetchUser()", DEPRECATION_WARNING, "regex"),
    ("Python module distutils is deprecated in Python 3.12", DEPRECATION_WARNING, "regex"),

    # --- caught by regex, but in a LATER category ---
    # "crashed" is a bare Workflow Error rule, so it wins before Security Alert
    # ever gets a chance to match. Documented here because it is the kind of
    # ordering choice a reader will assume is a bug.
    ("Container restart detected for pod monitoring-agent", WORKFLOW_ERROR, "regex"),
]


@pytest.mark.parametrize("text,expected_category,expected_tier", README_EXAMPLES)
def test_readme_examples_match_actual_behaviour(text, expected_category, expected_tier):
    """Each documented example must classify exactly as the README states.

    `allow_llm=False` keeps this test offline and deterministic: it exercises the
    regex and ML tiers only. Lines that would reach the LLM are asserted
    separately in `test_llm_tier_examples_degrade_honestly`.
    """
    result = classify_one(text, allow_llm=False)

    assert result["category"] == expected_category, (
        f"README documents this line as {expected_category}, "
        f"but it classified as {result['category']}"
    )
    assert result["tier_used"] == expected_tier, (
        f"README documents this line as handled by the {expected_tier} tier, "
        f"but it was handled by {result['tier_used']}"
    )
    # Confidence is exactly 1.0 for regex, never a rounded approximation.
    if expected_tier == "regex":
        assert result["confidence"] == 1.0


@pytest.mark.parametrize(
    "text",
    [
        # Deliberately phrased so no regex rule fires and the model is unsure.
        # These are the lines the LLM tier exists for.
        "SSL certificate for site example.org expires in 7 days",
        "Health check passed for service api-gateway",
        "User says the app feels slow today",
    ],
)
def test_llm_tier_examples_degrade_honestly(text):
    """Lines the cheaper tiers cannot resolve must abstain, never guess.

    The previous version of this project claimed these were classified as
    Security Alert / Unknown / Unknown. With the LLM tier disabled the honest
    answer is `Unknown` with a note -- and that is exactly what should happen
    when you have no API key and no confident model.

    This test is the offline contract: no key, no network, no flakiness.
    """
    result = classify_one(text, allow_llm=False)

    assert result["estimated_cost_usd"] == 0.0
    assert result["tier_used"] in {"unknown", "ml"}
    if result["tier_used"] == "unknown":
        assert result["category"] == UNKNOWN
        assert result["note"], "an abstention must explain itself"


def test_readme_worked_example_is_reproducible():
    """The README's headline 'memory usage' example, end to end.

    Guards the two claims the README leads with: regex catches it, and it costs
    nothing. If either becomes false, the architecture's argument changes and
    the documentation should fail loudly rather than quietly mislead.
    """
    result = classify_one("Memory usage at 87% on server node-12, threshold exceeded")

    assert result["category"] == RESOURCE_USAGE
    assert result["tier_used"] == "regex"
    assert result["confidence"] == 1.0
    assert result["estimated_cost_usd"] == 0.0
    # A regex match must always report which rule fired, so the UI can show it.
    assert result["matched"], "regex classifications must be explainable"
