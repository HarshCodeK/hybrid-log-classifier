import re

CATEGORIES = [
    "Security Alert",
    "Resource Usage",
    "Workflow Error",
    "Deprecation Warning",
    "Unknown"
]

REGEX_PATTERNS = {
    "Security Alert": [
        re.compile(r"(failed login|unauthorized access|brute force|sql injection|xss|malware|ransomware)", re.IGNORECASE),
        re.compile(r"(port scan|session hijack|data exfiltration|privilege escalation|account takeover)", re.IGNORECASE),
        re.compile(r"(login attempt|access attempt|blocked|firewall violation|invalid.*token)", re.IGNORECASE),
        re.compile(r"(certificate validation fail|two-factor authentication fail|attack detected)", re.IGNORECASE),
    ],
    "Resource Usage": [
        re.compile(r"(memory usage.*\d+%|cpu utilization.*\d+%|disk space.*\d+%|disk.*critical)", re.IGNORECASE),
        re.compile(r"(connection pool exhausted|swap memory|load average|thread pool)", re.IGNORECASE),
        re.compile(r"(bandwidth at|inode usage|disk i/o|temperature sensor|heap usage.*\d+%)", re.IGNORECASE),
        re.compile(r"(outbound queue|gpu memory exhausted|file descriptor limit|cache hit ratio)", re.IGNORECASE),
    ],
    "Workflow Error": [
        re.compile(r"(task queue.*fail|pipeline crash|workflow.*fail|job.*fail|data pipeline.*crash)", re.IGNORECASE),
        re.compile(r"(backup job.*fail|report generation.*fail|webhook.*fail|deployment.*rollback)", re.IGNORECASE),
        re.compile(r"(migration.*fail|sync.*fail|index rebuild.*fail|transcod.*abort|reindex.*fail)", re.IGNORECASE),
        re.compile(r"(timeout after|retry limit|unreachable after|certificate renewal.*fail)", re.IGNORECASE),
    ],
    "Deprecation Warning": [
        re.compile(r"(deprecated|deprecation)", re.IGNORECASE),
        re.compile(r"(end.of.life|end of life|will be removed|no longer supported)", re.IGNORECASE),
        re.compile(r"(migrate to|use.*instead|upgrade to)", re.IGNORECASE),
    ],
}

ML_CONFIDENCE_THRESHOLD = 0.6
