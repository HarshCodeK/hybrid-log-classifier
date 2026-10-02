"""Every tunable number, in one place."""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# The ML tier only answers when it is at least this confident. Below it, the
# tier returns "I don't know" instead of guessing -- see ml_tier.py.
ML_CONFIDENCE_THRESHOLD = 0.60

# Two log lines are the same incident when they share an entity AND fall
# within this many seconds of each other.
INCIDENT_WINDOW_SECONDS = 300

DB_PATH = os.environ.get("DB_PATH", "logs.db")
