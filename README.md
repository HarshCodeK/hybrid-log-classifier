# Hybrid Log Classifier

A log classification system that sorts log messages into 5 categories:
**Security Alert**, **Resource Usage**, **Workflow Error**, **Deprecation Warning**, and **Unknown**.

It uses a 3-tier approach (Regex → ML → LLM) to balance speed and cost.
Cheap checks run first; expensive LLM calls only happen when the simpler methods are unsure.

## Why 3 tiers?

Calling an LLM for every log line would be slow and expensive. Most logs follow
predictable patterns that can be caught with simple regex rules. For the rest,
a lightweight ML model (trained on labeled examples) handles the fuzzy cases.
The LLM is only used as a last resort when both regex and ML are not confident.
This keeps latency low and API costs near zero for common log patterns.

## Architecture

```
Log Line
  │
  ▼
┌─────────┐   Match?   ┌───────────┐
│  Regex   │──────────►│  Category  │
│ (Tier 1) │           └───────────┘
└────┬─────┘
     │ No match
     ▼
┌─────────┐  Conf ≥ 0.6? ┌───────────┐
│  ML /   │─────────────►│  Category  │
│  Embed  │              └───────────┘
└────┬─────┘
     │ Low confidence
     ▼
┌─────────┐             ┌───────────┐
│ Groq    │────────────►│  Category  │
│ LLM     │             └───────────┘
│ (Tier 3)│
└─────────┘
```

Each result (category, tier used, latency) is logged to SQLite.

## How to run

### 1. Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # add your GROQ_API_KEY
```

### 2. Train the ML model

```bash
python -c "from src.ml_classifier import train_model; train_model()"
```

Saves `models/classifier.pkl` and `models/label_encoder.pkl`.

### 3. Run the API

```bash
uvicorn api.main:app --reload
```

Then send a log line:

```bash
curl -X POST http://localhost:8000/classify \
  -H "Content-Type: application/json" \
  -d '{"text": "Multiple failed login attempts detected"}'
```

### 4. Run the Streamlit UI

```bash
streamlit run app.py
```

Opens a browser tab where you can type a log line or upload a CSV.

## Worked example

**Input:** `"Memory usage at 87% on server node-12, threshold exceeded"`

1. **Regex** — matches the pattern `memory usage.*\d+%` → **Resource Usage**
2. No need to check ML or LLM. Fast, zero cost.
3. Result: `{"category": "Resource Usage", "tier_used": "regex", "confidence": 1.0}`

**Input:** `"User says the app feels slow today"`

1. **Regex** — no pattern matches, returns `None`
2. **ML** — confidence is below 0.6 threshold → returns `(None, 0.42)`
3. **LLM** — classifies as "Unknown" (not clearly any category)
4. Result: `{"category": "Unknown", "tier_used": "llm", "confidence": null}`

## What I'd add next

- **Active learning loop** — feed high-confidence LLM predictions back into the ML training
  data to improve the model over time without manual relabeling.
- **Full Kaggle dataset** — train on a larger, real-world log dataset instead of 100
  synthetic samples to boost ML recall and reduce LLM calls further.
- **Per-category accuracy tracking** — monitor precision/recall per category over time
  by logging ground-truth labels when available, surfacing drift alerts.
