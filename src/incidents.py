"""Turn a wall of classified log lines into a short list of incidents.

This is the part that makes the tool worth using.

Classifying 4,000 log lines gives you 4,000 rows. Nobody reads 4,000 rows at
2am. What a person needs is: "there are six incidents, two are critical, start
with this one." That reduction is ordinary programming -- no model involved --
and it is where the real engineering value sits.

The grouping rule: two lines are the same incident when they share at least one
entity (host, user, IP, service) AND fall inside the same time window.

Both halves are necessary. Sharing an entity without a time bound would merge
every timeout for `db-01` across a whole week into one endless incident.
A time bound without a shared entity would merge unrelated errors that merely
happened at the same moment.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import re

from .config import ENTITY_PATTERNS, INCIDENT_WINDOW_SECONDS, SEVERITY, SEVERITY_ORDER


def extract_entities(text: str) -> set[str]:
    """Pull host / user / IP / service identifiers out of one log line.

    Each pattern returns the *value*, not the whole match, so
    "connection from user=alice" and "user alice logged in" both yield
    "alice" and therefore group together.

    Why prefixed keys (`host:node-12` rather than `node-12`): without them, a
    service literally named "admin" and a user named "admin" would be treated as
    the same entity and merge unrelated incidents.

    Why first-match-only per type: the overwhelming majority of lines mention at
    most one entity of each type. Taking every match would pull in incidental
    numbers and numbers as hostnames, which fragments groups that should merge.

    Why alternation is checked across groups: a pattern may have more than one
    capture group (the host pattern has a keyword form and a prefix form), and
    the first group that actually participated is the value. Using only
    `match.group(1)` would silently ignore every match from the second form.
    """
    found: set[str] = set()
    for entity_type, pattern in ENTITY_PATTERNS.items():
        match = pattern.search(text)
        if not match:
            continue
        # First non-empty group is the captured value for whichever alternative
        # matched. `lastindex` alone is not enough -- it reports the last
        # *participating* group but the earlier one may be the populated one.
        value = next(
            (group for group in match.groups() if group),
            None,
        )
        if value:
            found.add(f"{entity_type}:{value.lower()}")
    return found


def parse_timestamp(raw: str | None) -> datetime | None:
    """Parse a log timestamp, returning None when absent or unparseable.

    Tries a small set of common formats rather than depending on a date library,
    because log formats vary and the fallback is always the same: treat the line
    as having no time and place it in a single undated bucket.

    Why the naive datetime: all formats tried here are local server time with no
    timezone, and the only comparison this module makes is "is this within five
    minutes". That is unaffected by timezone handling.
    """
    if not raw:
        return None

    text = raw.strip().replace("T", " ").split("Z")[0]
    # Every format here carries an explicit year. The "%b %d %H:%M:%S" syslog
    # form does not, and parsing a year-less date is ambiguous enough that
    # Python 3.15 will stop accepting it by default -- so syslog lines are
    # handled separately below with an explicit year rather than risking a
    # runtime warning on every call.
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    # Syslog: "Sep 30 02:14:01" with no year. Parsed with a regex rather than
    # strptime because strptime cannot accept a year-less date without a
    # DeprecationWarning, and the warning becomes an error in Python 3.15.
    # The year is assumed to be the current one, which is right for log files
    # being read as they happen and is stated plainly rather than presented as
    # more precision than it has.
    syslog = _SYSLOG_RE.match(text)
    if syslog:
        try:
            return datetime(
                datetime.now().year,
                datetime.strptime(syslog.group("month"), "%b").month,
                int(syslog.group("day")),
                int(syslog.group("hour")),
                int(syslog.group("minute")),
                int(syslog.group("second")),
            )
        except ValueError:
            # Feb 29 in a non-leap year, or an out-of-range day.
            return None
    return None


# Syslog timestamp form: "Sep 30 02:14:01". No year, so it is matched rather
# than handed to strptime (which warns on year-less dates, and errors from
# Python 3.15). Kept next to parse_timestamp because it exists only to serve it.
_SYSLOG_RE = re.compile(
    r"^(?P<month>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})$"
)


class _Bucket:
    """A growing group of log lines that look like the same problem.

    Kept as a small class rather than a dict because it needs three pieces of
    mutable state that update together: the line count, the first and last
    timestamps, and the severity. Bundling them means there is one place where
    the accounting happens.
    """

    def __init__(self, category: str, severity: str):
        self.category = category
        self.severity = severity
        self.count = 0
        self.entities: set[str] = set()
        self.samples: list[str] = []
        self.first_seen: datetime | None = None
        self.last_seen: datetime | None = None
        self.cost_usd = 0.0

    def add(self, text: str, when: datetime | None, cost: float) -> None:
        self.count += 1
        self.entities |= extract_entities(text)
        self.cost_usd += cost
        if when is not None:
            if self.first_seen is None or when < self.first_seen:
                self.first_seen = when
            if self.last_seen is None or when > self.last_seen:
                self.last_seen = when
        # Keep a few real lines for the report. The first line of an incident is
        # usually the most informative, so cap the sample rather than storing
        # all 4,000.
        if len(self.samples) < 3:
            self.samples.append(text)

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "severity": self.severity,
            "line_count": self.count,
            "entities": sorted(self.entities),
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "duration_seconds": (
                int((self.last_seen - self.first_seen).total_seconds())
                if self.first_seen and self.last_seen
                else None
            ),
            "sample_lines": self.samples,
            "estimated_cost_usd": round(self.cost_usd, 6),
        }


def group_into_incidents(
    classified: list[dict], window_seconds: int = INCIDENT_WINDOW_SECONDS
) -> list[dict]:
    """Collapse classified log lines into incident buckets.

    ``classified`` is a list of dicts as produced by ``classify_batch`` --
    each with ``text``, ``category``, ``severity``, ``timestamp`` and
    ``estimated_cost_usd``.

    How the algorithm works, in order:

    1. **Index lines by entity.** Each line with at least one entity becomes a
       candidate to join an existing bucket.
    2. **Walk lines in time order.** For each line, look at the buckets its
       entities touch, and pick the most recent one that is still inside the
       time window.
    3. **Fall back on category when a line has no entities.** "Health check
       passed" has no host or user. Rather than dropping it, undated and
       entity-less lines are bucketed by category -- which still gives the
       operator a useful count of routine noise.
    4. **Prefer the worse severity.** If an incident contains both a Workflow
       Error and a Deprecation Warning, it is reported as a Workflow Error. A
       bucket should never be less urgent than its worst member.

    Why buckets track their own ``last_seen`` rather than comparing against the
    newest line overall: incidents in different parts of the file should not
    merge just because they are near each other in time. The comparison has to
    be against the bucket's own most recent entry.

    Why severity is compared by index rather than alphabetically: "critical"
    sorts before "high" alphabetically, but so does "high" before "info" and
    "medium" before "low". The ordering is a policy decision, so it is encoded
    explicitly in config.SEVERITY_ORDER.
    """
    buckets: list[_Bucket] = []
    # Index from entity-set to the list of buckets mentioning it. A LIST, not a
    # dict keyed by entity set: two incidents can share an entity and be hours
    # apart, and keying by entity alone silently overwrote the first with the
    # second. Keeping every candidate and choosing by time window is what makes
    # the split work.
    entity_index: dict[str, list[_Bucket]] = defaultdict(list)

    # Sort by time when available so the window comparison below is meaningful.
    # Lines with no timestamp sort last and form their own undated buckets.
    #
    # The key function is defensive about the (text, timestamp) vs
    # (timestamp, text) argument order, because getting it backwards silently
    # classifies every line as Unknown and collapses the whole batch into one
    # incident -- a failure that looks like working code. If the first field
    # parses as a timestamp and the second does not, swap them.
    def normalize(item: dict) -> tuple[str, str | None]:
        text, timestamp = item.get("text", ""), item.get("timestamp")
        if timestamp is not None and parse_timestamp(text) is not None:
            if parse_timestamp(timestamp) is None:
                return timestamp, text
        return text, timestamp

    def sort_key(item: dict):
        text, timestamp = normalize(item)
        parsed = parse_timestamp(timestamp)
        return (parsed is None, parsed or datetime.min, text)

    for item in sorted(classified, key=sort_key):
        text, timestamp = normalize(item)
        category = item["category"]
        severity = item.get("severity") or SEVERITY.get(category, "info")
        when = parse_timestamp(timestamp)
        cost = float(item.get("estimated_cost_usd") or 0.0)

        entities = frozenset(extract_entities(text))

        # How this line is looked up in a moment. A line with no entities falls
        # back to its category, so undated routine lines accumulate into one
        # bucket instead of making a fresh incident each -- which would defeat
        # the point of grouping. The `|` join is used so a category key can never
        # collide with an entity key.
        grouping_key = "|".join(sorted(entities)) if entities else f"|category|{category}"

        # Candidate buckets: any bucket sharing at least one entity with this
        # line that is still inside the time window, preferring the most
        # recently active one so a burst extends its own incident instead of
        # hopping between two.
        best_bucket = None
        candidates: dict[int, _Bucket] = {}
        for key in ([grouping_key] if not entities else list(entities)):
            for bucket in entity_index.get(key, []):
                candidates[id(bucket)] = bucket

        for bucket in candidates.values():
            if when is not None and bucket.last_seen is not None:
                gap = when - bucket.last_seen
                if gap > timedelta(seconds=window_seconds):
                    continue
            if best_bucket is None:
                best_bucket = bucket
            elif bucket.last_seen is None:
                best_bucket = bucket
            elif when is not None and bucket.last_seen is not None:
                if bucket.last_seen > best_bucket.last_seen:
                    best_bucket = bucket

        # No in-window match: this line starts a new incident.
        if best_bucket is None:
            best_bucket = _Bucket(category, severity)
            buckets.append(best_bucket)
            entity_index[grouping_key].append(best_bucket)

        best_bucket.add(text, when, cost)

        # Index this line's own entities too, so a later line can find this
        # bucket by any entity it mentions and not only by the key that created
        # it. Without this, a line joining on `ip` would not be findable later
        # via `user`, and the incident would split for no good reason.
        for entity in entities:
            if best_bucket not in entity_index[entity]:
                entity_index[entity].append(best_bucket)

        # Promote severity if this line is worse than everything seen so far.
        if SEVERITY_ORDER.index(severity) < SEVERITY_ORDER.index(best_bucket.severity):
            best_bucket.severity = severity

    # Severity first, then volume: a single critical line outranks forty
    # low-severity ones, because it is the one that gets looked at.
    incidents = [bucket.to_dict() for bucket in buckets]
    incidents.sort(
        key=lambda item: (SEVERITY_ORDER.index(item["severity"]), -item["line_count"])
    )
    return incidents
