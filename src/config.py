"""Where to draw the line between "sure" and "not sure".

Everything tunable in this project lives here so that the logic files contain
only logic. If you want to change how the system behaves, this is the one file
to open.

Why a separate file: when a threshold is buried inside a classifier, nobody can
tell what the system is actually doing. Keeping them here means the behaviour
of the whole project can be read in one sitting.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------
# The five categories
# --------------------------------------------------------------------------

SECURITY_ALERT = "Security Alert"
RESOURCE_USAGE = "Resource Usage"
WORKFLOW_ERROR = "Workflow Error"
DEPRECATION_WARNING = "Deprecation Warning"
UNKNOWN = "Unknown"

CATEGORIES = [
    SECURITY_ALERT,
    RESOURCE_USAGE,
    WORKFLOW_ERROR,
    DEPRECATION_WARNING,
    UNKNOWN,
]

# --------------------------------------------------------------------------
# Tier 1: regex patterns
# --------------------------------------------------------------------------
#
# These are written out one per line rather than packed into a single pattern.
# It is more lines, but you can read a single rule, understand it, and edit it
# without touching the others. Packing ten alternatives into one string means a
# typo in any one of them is nearly impossible to find.
#
# The order of the lists below matters: `classify_with_regex` returns the first
# category that has any match, so put the most specific category first.


def _c(pattern: str) -> re.Pattern:
    """Compile a pattern case-insensitively.

    Log lines are inconsistent about capitalisation ("ERROR", "error", "Error"),
    so every rule ignores case. Keeping that in one helper means no individual
    pattern can forget it.
    """
    return re.compile(pattern, re.IGNORECASE)


REGEX_PATTERNS: dict[str, list[re.Pattern]] = {
    # A specific failure ("failed login", "unauthorized") outranks the vague
    # ("blocked"), so this category is checked before Resource Usage and
    # Workflow Error -- both of which contain the word "fail" in places.
    SECURITY_ALERT: [
        # Someone did not get in.
        _c(r"failed login"),
        _c(r"unauthori[sz]ed"),
        _c(r"invalid (credentials|password|token)"),
        _c(r"authentication fail"),
        _c(r"access denied"),
        _c(r"brute[- ]?force"),
        _c(r"two[- ]factor .*(fail|reject)"),
        # Something is actively probing or attacking.
        _c(r"port scan"),
        _c(r"sql injection"),
        _c(r"\bxss\b"),
        _c(r"malware"),
        _c(r"ransomware"),
        _c(r"data exfiltration"),
        _c(r"privilege escalation"),
        _c(r"account takeover"),
        _c(r"(attack|intrusion) detected"),
        # Someone was blocked. Checked late in the list because "blocked" also
        # shows up in resource errors ("connection blocked").
        _c(r"\bblocked\b"),
    ],
    RESOURCE_USAGE: [
        # A resource crossed a percentage threshold. The number is required --
        # without it, "memory usage" alone would also match prose about memory.
        _c(r"(memory|cpu|disk|heap|gpu) (usage|utilization) .*\d+%"),
        _c(r"\d+% (of )?(memory|cpu|disk|heap)"),
        _c(r"disk space.*\d+%"),
        _c(r"disk (space )?(critical|full)"),
        _c(r"out of memory"),
        _c(r"oom[- ]?kill"),
        # Saturation words, which carry the meaning without a number.
        _c(r"(connection|thread|file descriptor) pool (exhausted|full)"),
        _c(r"cache hit ratio"),
        _c(r"load average"),
        _c(r"swap memory"),
        _c(r"resource exhaustion"),
        _c(r"bandwidth (at|saturated)"),
        _c(r"\d+% capacity"),
    ],
    WORKFLOW_ERROR: [
        # A named unit of work failed.
        _c(r"(task|job|workflow|pipeline|etl|backup|migration|sync) .*fail"),
        _c(r"(task|job|workflow|pipeline) .*(crash|abort)"),
        _c(r"pipeline crash"),
        _c(r"data pipeline crash"),
        # Something died unexpectedly.
        _c(r"crashed"),
        _c(r"unexpected error"),
        _c(r"exception occurred"),
        _c(r"unhandled exception"),
        # Timeouts and retry exhaustion.
        _c(r"timed? ?out"),
        _c(r"timeout after"),
        _c(r"retry limit (reached|exceeded)"),
        _c(r"deadline exceeded"),
        # An orchestrator restarting a unit is a workflow failure, not a
        # resource one, even though it often causes resource pressure.
        _c(r"(container|pod|service) restart"),
        _c(r"deployment (rollback|failed)"),
    ],
    DEPRECATION_WARNING: [
        # The literal word is a strong enough signal on its own.
        _c(r"deprecat(ed|ion)"),
        _c(r"end[- ]of[- ]life"),
        _c(r"no longer supported"),
        _c(r"will be (removed|retired|sunset)"),
        # "use X instead" is the standard shape of a deprecation notice.
        _c(r"use \w+ instead"),
        _c(r"migrate to"),
        _c(r"(obsolete|superseded|replaced by)"),
        _c(r"sunset(ting)? date"),
    ],
}

# --------------------------------------------------------------------------
# Tier 2: the ML confidence threshold
# --------------------------------------------------------------------------
#
# This is the single most important number in the project.
#
# Too low  -> the ML model claims categories it has not really learned, and the
#             LLM tier almost never runs. You save money and lose accuracy.
# Too high -> the LLM runs far more often than it needs to. You pay for
#             intelligence you already had.
#
# 0.6 is measured, not guessed. See docs/03-tech-stack.md for the numbers at
# 0.5 / 0.6 / 0.7 and why 0.6 is the operating point.
ML_CONFIDENCE_THRESHOLD = 0.60

# --------------------------------------------------------------------------
# Incident severity
# --------------------------------------------------------------------------
#
# Deliberately a lookup table rather than a model. "How bad is a security
# alert" is a business decision, not something to learn from 100 examples.
#
# UNKNOWN gets a real severity on purpose. Routing unknown lines to a human is
# the correct behaviour for an operations tool -- silently discarding them
# would be the dangerous choice.
SEVERITY = {
    SECURITY_ALERT: "critical",
    WORKFLOW_ERROR: "high",
    RESOURCE_USAGE: "medium",
    DEPRECATION_WARNING: "low",
    UNKNOWN: "info",
}

# Ranked worst-first. The UI sorts incidents by this.
SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]

# --------------------------------------------------------------------------
# Entities extracted for incident grouping
# --------------------------------------------------------------------------
#
# Two log lines belong to the same incident when they mention the same host,
# user, or IP. Pulling those out is what lets a wall of 4,000 lines collapse
# into a few dozen real incidents.
#
# Capturing groups rather than single values matters: "IP blocked for
# 1.2.3.4" and "IP 5.6.7.8 blocked" are different incidents even though the
# messages are nearly identical.
ENTITY_PATTERNS = {
    # Host names need two patterns, and the reason is worth spelling out.
    #
    # A naive `node[- ]?(\w+)` matches the keyword "node" inside the host name
    # "node-12" and captures only "12" -- so "node-12" and "db-12" become
    # different entities while "node-12" and "node-12 (restart)" do not. The
    # hyphen is part of the name, not a separator between keyword and value.
    #
    # So: a keyword form that requires real whitespace ("server db-01" ->
    # "db-01"), plus a prefix form that keeps the whole hyphenated token
    # ("node-12" -> "node-12").
    #
    # Note `api-` is deliberately NOT in the prefix list. "api-gateway" is a
    # service, and listing it here as well made every "service api-gateway"
    # line register under two entity types at once -- inflating the entity set
    # and splitting incidents that should have merged.
    "host": re.compile(
        r"\b(?:host|server|instance)\s+([\w.-]+)"      # "server db-01"
        r"|\b((?:node|db|web|app|worker|cache|gpu)-[\w.-]+)",  # "node-12"
        re.IGNORECASE,
    ),
    "user": re.compile(r"\buser(?:name)?\s+([\w.-]+)", re.IGNORECASE),
    "ip": re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"),
    "service": re.compile(r"\b(?:service|pod|container)\s+([\w.-]+)", re.IGNORECASE),
}

# How close two log lines must be, in seconds, to be considered part of the
# same burst. Beyond this window the same error is a new incident -- a
# connection timeout at 09:00 and at 14:00 are different problems even if the
# message is character-for-character identical.
INCIDENT_WINDOW_SECONDS = 300
