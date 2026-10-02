"""Train the ML tier and report both accuracy numbers.

Run:  python train.py
"""
import sys

from src.ml_tier import train

if __name__ == "__main__":
    leaky, honest = train("data/training_logs.csv")
    print()
    print(f"Quote {honest:.3f} in an interview, not {leaky:.3f}.")
    print("The random split can leak repeated template phrasing across both sides.")
    sys.exit(0)
