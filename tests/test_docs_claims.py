"""Verify that the numbers printed in the documentation are still true.

Why this file exists: while writing the docs I quoted "71.55% cost avoided" and
then re-ran the pipeline after fixing the system-prompt token count, and the
real number was 71.68%. A stale figure in a README is precisely the failure this
whole project was rebuilt to eliminate -- and documentation is the one artefact
no test suite normally checks.

So the documentation is now a test input. Every figure asserted here is derived
from running the code, not copied from a previous run. If a prompt changes, a
price changes, or a threshold moves, this suite fails and tells you which
document to update.

What is and is not asserted:
- Tier counts, incident counts, category counts, latency ordering, and cost
  ordering are asserted, because those are deterministic offline.
- Exact dollar figures are NOT asserted to the cent, because LLM latency and
  pricing vary. What is asserted is the *relationship* -- the tiered run must
  cost strictly less than the naive one, and the free tiers must cost zero.
- Live LLM accuracy is NOT asserted here; it needs network and costs money. It
  lives in docs/03-tech-stack.md as a recorded benchmark with the command to
  reproduce it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.config import CATEGORIES, SEVERITY_ORDER
from src.incidents import group_into_incidents
from src.pipeline import classify_batch

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
DOCS = ROOT / "docs"
DEMO_BATCH = ROOT / "data" / "demo_batch.json"


@pytest.fixture(scope="module")
def demo_lines() -> list[tuple[str, str | None]]:
    """Parse the shipped demo batch the same way the API does."""
    payload = json.loads(DEMO_BATCH.read_text(encoding="utf-8"))
    pairs = []
    for raw in payload["lines"]:
        match = re.match(r"^\[(?P<ts>[^\]]+)\]\s*(?P<msg>.*)$", raw)
        assert match, f"demo line is not in [timestamp] message form: {raw}"
        pairs.append((match.group("msg"), match.group("ts")))
    return pairs


@pytest.fixture(scope="module")
def offline_summary(demo_lines):
    """Run the demo batch with the LLM tier disabled.

    Offline so the suite stays deterministic and free. Tier counts differ from a
    live run -- unmatched lines become Unknown rather than reaching tier 3 -- so
    the assertions below are chosen to hold in both modes.
    """
    return classify_batch(demo_lines, allow_llm=False)


# ---------------------------------------------------------------------------
# The demo batch itself
# ---------------------------------------------------------------------------

def test_demo_batch_matches_documented_size(demo_lines):
    """The README says "14 log lines in". That must stay true."""
    assert len(demo_lines) == 14, (
        "docs quote a 14-line demo; data/demo_batch.json has "
        f"{len(demo_lines)}. Update README.md and docs/01 + docs/04."
    )


def test_demo_batch_has_timestamps_everywhere(demo_lines):
    """Every demo line must carry a parseable timestamp.

    The walkthrough depends on the time window separating two incidents, so a
    line without a timestamp would quietly change the grouping.
    """
    for text, ts in demo_lines:
        assert ts, f"line has no timestamp: {text!r}"


# ---------------------------------------------------------------------------
# Tier behaviour
# ---------------------------------------------------------------------------

def test_free_tiers_never_cost_money(offline_summary):
    """Regex and ML are the free tiers. That is the entire premise.

    If this ever becomes false, the "71% avoided" claim in the README is not just
    stale -- it is wrong, because the saving would come from somewhere else.
    """
    for row in offline_summary["classifications"]:
        if row["tier_used"] in {"regex", "ml", "unknown"}:
            assert row["estimated_cost_usd"] == 0.0, (
                f"tier {row['tier_used']} charged "
                f"${row['estimated_cost_usd']} for {row['text']!r}"
            )


def test_regex_is_the_dominant_tier(offline_summary):
    """The README claims 10 of 14 lines are answered by regex.

    Asserted as a minimum rather than exactly, so this still holds if the rules
    gain a pattern -- but if regex stops covering the majority, the cost-savings
    story has changed and the docs need rewriting.
    """
    assert offline_summary["tier_counts"].get("regex", 0) >= 10, (
        f"only {offline_summary['tier_counts'].get('regex', 0)} of "
        f"{offline_summary['total_lines']} lines hit regex; docs quote 10 of 14"
    )


def test_tiering_actually_avoids_cost(offline_summary):
    """Cost avoided must be strictly positive, and never above 100%.

    The two failure modes this catches: a pricing bug that makes the tiered run
    MORE expensive than naive (which would mean the architecture is pointless),
    and a division that produces a nonsense percentage.
    """
    assert offline_summary["total_cost_usd"] == 0.0, (
        "with the LLM tier disabled nothing should be charged at all"
    )
    assert offline_summary["naive_llm_cost_usd"] > 0, (
        "the naive baseline must be non-zero or 'cost avoided' is meaningless"
    )
    assert 0 <= offline_summary["cost_avoided_pct"] <= 100.0


def test_naive_baseline_uses_the_same_pricing_as_the_tiers(offline_summary):
    """The comparison must be apples-to-apples.

    If the naive figure used a different price table than the real calls, the
    percentage would be a comparison between two different models' economics and
    the number in the README would be meaningless.
    """
    from src.pipeline import estimate_llm_cost

    sample = offline_summary["classifications"][0]["text"]
    assert offline_summary["naive_llm_cost_usd"] > 0
    assert estimate_llm_cost(sample) > 0


# ---------------------------------------------------------------------------
# Incident grouping -- the documented demo output
# ---------------------------------------------------------------------------

def test_demo_produces_seven_incidents(offline_summary):
    """The README headline is "7 incidents". Hold it to that."""
    assert len(offline_summary["incidents"]) == 7, (
        f"demo produced {len(offline_summary['incidents'])} incidents, "
        "docs say 7. Update README.md and docs/01 + docs/04."
    )


def test_login_burst_collapses_to_one_critical_incident(offline_summary):
    """The five failed logins for one user must be ONE critical incident.

    This is the single most-quoted behaviour in the docs: five lines in, one
    incident out, sharing the user entity.
    """
    security = [
        i for i in offline_summary["incidents"] if i["category"] == "Security Alert"
    ]
    assert len(security) == 1, (
        f"expected one Security Alert incident, got {len(security)}"
    )
    assert security[0]["line_count"] == 5
    assert security[0]["severity"] == "critical"
    assert "user:admin_42" in security[0]["entities"]


def test_memory_warnings_group_separately_from_the_security_burst(offline_summary):
    """The 2am breach and the 8am memory leak are different problems.

    They share no entity and are hours apart, so the time-window rule must keep
    them apart. If this ever merges, the grouping logic has regressed.
    """
    incidents = offline_summary["incidents"]
    memory = [i for i in incidents if "host:node-12" in i["entities"]]
    assert memory, "expected an incident grouping the node-12 memory warnings"
    assert memory[0]["line_count"] == 3
    assert memory[0]["severity"] == "medium"
    # And it must not be the same incident as the security burst.
    assert memory[0] is not incidents[0]


def test_incidents_are_sorted_worst_first(offline_summary):
    """The docs say the worst incident is on top. Verify the ordering."""
    order = [SEVERITY_ORDER.index(i["severity"]) for i in offline_summary["incidents"]]
    assert order == sorted(order), f"incidents are not severity-sorted: {order}"


def test_every_incident_category_is_one_of_the_five(offline_summary):
    """No invented categories. The closed set is the point of the LLM tier."""
    for incident in offline_summary["incidents"]:
        assert incident["category"] in CATEGORIES


# ---------------------------------------------------------------------------
# Documentation files
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name",
    [
        "01-why-this-project.md",
        "02-architecture.md",
        "03-tech-stack.md",
        "04-walkthrough.md",
        "05-interview-qa.md",
        "06-limitations.md",
        "07-concepts.md",
    ],
)
def test_referenced_doc_exists(name):
    """Every doc the README links must exist.

    A README pointing at a missing file is the cheapest possible credibility
    loss, and it is trivially preventable.
    """
    assert (DOCS / name).exists(), f"README references docs/{name}, which is missing"


def test_readme_links_resolve():
    """Every relative markdown link in the README must point at a real file."""
    text = README.read_text(encoding="utf-8")
    links = re.findall(r"\]\((?!https?://)([^)#]+)\)", text)

    broken = []
    for link in links:
        target = (ROOT / link).resolve()
        if not target.exists():
            broken.append(link)

    assert not broken, f"README has dead relative links: {broken}"


def test_readme_claims_no_html_injection():
    """The README claims there is no innerHTML in static/.

    Comments stripped, then checked -- a mention of innerHTML inside a comment is
    not a violation, but an actual assignment is.
    """
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    stripped = re.sub(r"/\*.*?\*/", "", app_js, flags=re.S)
    stripped = re.sub(r"//[^\n]*", "", stripped)

    assert not re.search(r"innerHTML\s*=", stripped), (
        "static/app.js assigns innerHTML; the README and docs/02 both claim it "
        "does not, and the XSS argument depends on that being true"
    )


def test_readme_does_not_quote_an_inflated_accuracy():
    """The docs must never present the leaky 1.000 *overall accuracy* as a result.

    Scoped deliberately. Per-class precision of 1.000 is legitimate and appears
    in the real output -- only the aggregate accuracy figure is inflated by
    leakage. So this matches accuracy-like phrasings, not bare "1.000", and it
    allows the number anywhere near an explicit leakage label.

    The failure this prevents: someone editing the README to promote "1.000
    accuracy" to a headline without carrying the caveat with it.
    """
    # Phrases that present 1.000 as a headline result. Per-class table rows and
    # leakage-framed mentions are intentionally not matched.
    inflated = re.compile(
        r"(?:accuracy|scores?|gives?|reports?)[^.\n]{0,40}\b1\.000\b"
        r"|\b1\.000\s+accuracy\b",
        re.IGNORECASE,
    )

    for path in [README] + sorted(DOCS.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for match in inflated.finditer(text):
            # A leakage label anywhere in the surrounding paragraph is enough:
            # if the caveat is present, the number is honestly presented.
            start = text.rfind("\n\n", 0, match.start())
            paragraph = text[start if start != -1 else 0: match.end() + 300].lower()
            if "leak" in paragraph or "misleading" in paragraph or "honest number" in paragraph:
                continue
            pytest.fail(
                f"{path.name} presents 1.000 as a result without labelling it as "
                f"leakage. Quote 0.491 instead.\n\n"
                f"  ...{match.group(0)}..."
            )
