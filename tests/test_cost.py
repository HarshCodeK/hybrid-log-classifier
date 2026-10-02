"""Tests for cost estimation.

Cost is the number this project exists to defend, so it gets tested like one.

The regression that prompted this file: the cost table was originally two bare
constants carrying Llama-3.3-70b's published rates. When the deployed model
changed to qwen3.8-27b, those constants were never updated -- so every cost
figure the tool reported was wrong by roughly 6x on input tokens, and nothing
failed. The reported number looked plausible because it was the wrong number.

These tests pin the behaviour that would have caught it.
"""

from __future__ import annotations

import pytest

from src.pipeline import MODEL_PRICES, _price_for, estimate_llm_cost


def test_cost_is_priced_per_model_not_globally():
    """Two models with different prices must produce different costs.

    This is the direct guard against the regression: a single hardcoded constant
    cannot pass this test, because it would return one price for both models
    regardless of which one actually answered.

    Both models compared here are LIVE. An earlier version of this test used
    llama-3.3-70b-versatile as the "expensive" example, which quietly became
    wrong when Groq retired it and the real qwen rate turned out to be far
    higher -- the test then failed for a reason unrelated to what it was
    checking. A guard should not depend on a price that changes under it.
    """
    cheap = estimate_llm_cost("Disk nearly full", model="openai/gpt-oss-20b")
    expensive = estimate_llm_cost("Disk nearly full", model="qwen/qwen3.8-27b")

    assert cheap < expensive, (
        "openai/gpt-oss-20b is priced below qwen/qwen3.8-27b, so it must cost "
        "less; equal costs mean the price table is being ignored"
    )
    assert cheap > 0


def test_published_rates_match_groq():
    """Pin the rates to Groq's published prices, checked 2026-10-02.

    Added after the table claimed qwen/qwen3.8-27b cost $0.10/$0.30 per 1M
    when the real rate is $0.80/$4.00 -- an 8x understatement that made every
    "cost avoided" figure too small while nothing failed.
    """
    published = {
        "qwen/qwen3.8-27b": (0.80, 4.00),
        "openai/gpt-oss-120b": (0.15, 0.60),
        "openai/gpt-oss-20b": (0.075, 0.30),
    }
    for model, (pin, pout) in published.items():
        assert MODEL_PRICES[model] == (pin, pout), (
            f"{model} is priced {MODEL_PRICES[model]} but Groq publishes "
            f"{(pin, pout)} per 1M tokens"
        )


def test_unknown_model_defaults_to_the_pessimistic_rate():
    """An unpriced model must not make the estimate look cheaper than reality.

    The fallback is set to the most expensive live rate on purpose: a wrong
    price that flatters the project is worse than one that overstates it.
    """
    unknown = estimate_llm_cost("some log line", model="some/model-from-tomorrow")
    dearest_live = max(
        estimate_llm_cost("some log line", model=m) for m in MODEL_PRICES
        if m != "llama-3.3-70b-versatile"
    )
    assert unknown >= dearest_live


def test_unknown_model_falls_back_instead_of_raising():
    """An unpriced model must degrade, not crash the batch.

    Cost is a reporting concern. A model released tomorrow that is missing from
    the table should produce a default-price estimate, not take down a
    classification that otherwise succeeded.
    """
    cost = estimate_llm_cost("some log line", model="some/model-released-tomorrow")
    assert cost > 0, "a fallback price must still produce a usable estimate"


def test_system_prompt_estimate_is_current():
    """The cost estimate must track the real prompt length.

    Added after the estimate was hardcoded at 230 tokens while the actual prompt
    is ~299 -- a 30% understatement on every LLM call, which is exactly the
    number the project exists to defend. The estimate is now measured from the
    prompt at call time, and this test asserts the fallback is close to the real
    value so a future edit that breaks the lazy import is caught.

    The fallback exists for the case where the import fails; if it ever drifts
    from reality the number is wrong and nothing else would notice.
    """
    from src.llm_classifier import SYSTEM_PROMPT
    from src.pipeline import SYSTEM_PROMPT_TOKENS_FALLBACK, _system_prompt_tokens

    actual = _system_prompt_tokens()
    # The fallback must be within 25% of the measured value.
    assert abs(SYSTEM_PROMPT_TOKENS_FALLBACK - actual) / actual < 0.25, (
        f"fallback {SYSTEM_PROMPT_TOKENS_FALLBACK} is too far from the measured "
        f"{actual} tokens; update SYSTEM_PROMPT_TOKENS_FALLBACK"
    )
    # And the measured value must be derived from the prompt, not hardcoded.
    assert actual == len(SYSTEM_PROMPT) // 4


def test_cost_has_a_floor_from_the_system_prompt():
    """Even a one-character log line costs something, because the prompt does.

    The system prompt is ~230 tokens and is charged on every call. If a very
    short line cost the same as a very long one, the prompt would be missing
    from the estimate -- which would make short-line batches look artificially
    cheap.
    """
    short = estimate_llm_cost("x")
    long = estimate_llm_cost("x" * 400)
    assert long > short
    # A 1-char line is essentially pure system-prompt cost.
    assert short > MODEL_PRICES["qwen/qwen3.8-27b"][0] / 1_000_000 * 100


def test_price_lookup_is_exact_match_not_substring():
    """A model name must match a table key exactly.

    Substring matching would let `llama-3.3-70b-versatile-tuned` pick up the
    base model's price, which is a quiet way to be wrong about money.
    """
    assert _price_for("openai/gpt-oss-20b") != _price_for("openai/gpt-oss-120b")
    assert _price_for("openai/gpt-oss-20b") == MODEL_PRICES["openai/gpt-oss-20b"]


def test_retired_model_price_is_retained_for_reproducibility():
    """The retired Llama entry must stay in the table.

    Removing it would make an old deployment's stored reports impossible to
    reproduce, and quietly re-price past data. Keeping a dead model's price with
    a comment saying it is retired is the honest option.
    """
    assert "llama-3.3-70b-versatile" in MODEL_PRICES


@pytest.mark.parametrize("model", list(MODEL_PRICES))
def test_every_price_is_plausible(model):
    """Guard against typos like a missing decimal point.

    A price entered as 0.10 rather than 0.10 is fine; 10 rather than 0.10 would
    make the cost panel off by 100x and still look like a number.
    """
    input_price, output_price = MODEL_PRICES[model]
    assert 0 < input_price < 10, f"{model} input price looks like a typo: {input_price}"
    assert 0 < output_price < 10, f"{model} output price looks like a typo: {output_price}"
    # Output tokens cost more than input on every model here; that is the usual
    # shape and an inversion almost always means a swapped pair.
    assert output_price >= input_price


def test_zero_length_text_still_costs_something():
    """An empty log line is nonsense input, but must not divide by zero."""
    cost = estimate_llm_cost("")
    assert cost >= 0
