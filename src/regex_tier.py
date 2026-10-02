"""Tier 1: pattern matching. Free, instant, and correct when it fires.

Why regex first: it costs nothing and it is not a guess. A line containing
"failed login for user X" needs no model to know that is a security event.
Sending that to an LLM would cost money to be told what a substring already said.
"""
import re

# (category, pattern). Order matters -- first match wins, so the specific
# patterns come before the general ones.
PATTERNS = [
    ("Security Alert", r"failed login|authentication failure|access denied|unauthori[sz]ed|brute.?force"),
    ("Resource Usage", r"memory usage|cpu usage|disk (?:usage|full)|threshold exceeded|out of memory|eviction failed"),
    ("Deprecation Warning", r"deprecat"),
    ("Workflow Error", r"\bfailed\b|\berror\b|\bexception\b|timed out|connection reset"),
]

# Two rules these patterns follow, each learned from a bug:
#
# 1. Every pattern requires a keyword. Without one, the bare word "admin" in
#    "admin panel" gets read as a username.
# 2. The host pattern allows an optional filler word ("on server node-12") and
#    requires a hostname-shaped token. A bare "on <word>" alternative captured
#    "server" instead of the hostname; a loose alternative matched
#    "service admin" and stopped the service pattern from ever running.
ENTITY_PATTERNS = {
    "user": r"\b(?:user|username)\s*[=:]?\s*([\w.-]+)",
    "ip": r"\b(?:from|in)\s+(?:ip\s+)?(\d{1,3}(?:\.\d{1,3}){3})",
    "host": r"\b(?:on|from|host)\s+(?:server\s+)?((?:node|db|web|cache|api|worker)[\w.-]*)",
    "service": r"\bservice\s+([\w.-]+)",
}

_COMPILED = [(cat, re.compile(pat, re.I)) for cat, pat in PATTERNS]
_ENTITIES = {k: re.compile(pat, re.I) for k, pat in ENTITY_PATTERNS.items()}

SEVERITY = {
    "Security Alert": "critical",
    "Workflow Error": "high",
    "Resource Usage": "medium",
    "Deprecation Warning": "low",
    "Unknown": "low",
}


def classify(line: str):
    """Return (category, severity, matched_text) or None if nothing matches."""
    for category, rx in _COMPILED:
        m = rx.search(line)
        if m:
            return category, SEVERITY[category], m.group(0)
    return None


def extract_entities(line: str) -> set:
    """Pull identifiers out of a line so related lines can be grouped.

    Returns prefixed keys ("user:alice") rather than bare values, so a service
    named "admin" and a user named "admin" do not merge into one incident.
    """
    found = set()
    for kind, rx in _ENTITIES.items():
        m = rx.search(line)
        if m:
            found.add(f"{kind}:{m.group(1).lower()}")
    return found
