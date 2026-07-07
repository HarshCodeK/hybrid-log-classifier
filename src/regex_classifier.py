from src.config import REGEX_PATTERNS


def classify_regex(text: str):
    for category, patterns in REGEX_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(text):
                return category
    return None


if __name__ == "__main__":
    test_lines = [
        "Multiple failed login attempts detected for user admin_42",
        "Memory usage at 87% on server node-12, threshold exceeded",
        "Task queue processing failed for job ID 8823, retry limit reached",
        "Function getUserData() is deprecated, use fetchUser() instead",
        "User jdoe logged in from Chrome on Windows 10",
    ]
    for line in test_lines:
        result = classify_regex(line)
        print(f"{result or 'No match':20s} | {line}")
