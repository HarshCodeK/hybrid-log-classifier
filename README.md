# Hybrid Log Classifier

A deliberately small, explainable log classifier: Regex → TF-IDF + Logistic Regression → optional Groq LLM. The Streamlit UI and FastAPI endpoint use the same classifier. Results are stored locally in SQLite.

## Ten alarm categories

security, availability, performance, resource_exhaustion, database, network, deployment, data_integrity, configuration, dependency_failure. The result unknown is an abstention, not an eleventh trained category.

## Exactly when each stage runs

1. Regex first: high-precision known signatures are checked in order. A match returns immediately with tier regex; ML and Groq are skipped.
2. ML second: if no regex matches, a scikit-learn Pipeline trained at startup from data/training.csv uses word/bigram TF-IDF and Logistic Regression. ML is accepted only if the text has terms in the learned vocabulary and the maximum class probability is at least ML_CONFIDENCE_THRESHOLD (default 0.45).
3. Groq last: if the text has no terms known to the model or ML confidence is below threshold, the app calls Groq only when GROQ_API_KEY is set. The configured model is openai/gpt-oss-20b. If the key is missing or the request fails, the app returns unknown with an explicit tier/reason; it never pretends an LLM ran.

The confidence threshold is a demo routing heuristic, not a measured or calibrated probability guarantee.

## Windows setup (PowerShell)

Run from the repository root, the folder containing requirements.txt:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Open .env and add your Groq key to GROQ_API_KEY= if you want LLM escalation. Get a key at https://console.groq.com/keys. Never commit .env.

## Run the frontend

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open the local URL Streamlit prints, usually http://localhost:8501.

## Run the API (optional)

Only needed if you want to demonstrate the API separately; Streamlit does not require it.

```powershell
.\.venv\Scripts\python.exe -m uvicorn hybrid_log_classifier.api:app --reload
```

API docs: http://127.0.0.1:8000/docs. Health endpoint: http://127.0.0.1:8000/health.

## Run tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Tests cover the real model and all ten labels, regex routing, ML routing, Groq escalation (mocked so tests spend no API credits), missing-key abstention, and the API smoke path.

## Test prompts and expected route

| Route | Prompt | Expected behavior |
|---|---|---|
| Regex → security | Failed login for user=alice from 203.0.113.8 | security / regex |
| Regex → availability | Health check failed for checkout service | availability / regex |
| Regex → performance | P95 latency spike exceeded alert limit | performance / regex |
| Regex → resource | OOMKilled: container exceeded memory limit | resource_exhaustion / regex |
| Regex → database | Database deadlock detected while committing transaction | database / regex |
| Regex → network | DNS resolution failed for api.internal | network / regex |
| Regex → deployment | Rollout failed for payments release | deployment / regex |
| Regex → integrity | Checksum mismatch detected for stored object | data_integrity / regex |
| Regex → configuration | Missing environment variable PAYMENT_SECRET | configuration / regex |
| Regex → dependency | Circuit breaker opened after upstream dependency failures | dependency_failure / regex |
| ML | The endpoint response time became sluggish during peak traffic | ML should classify performance if confidence clears threshold; no exact regex phrase |
| ML | The host is exhausting available RAM and swap while requests continue | ML should classify resource exhaustion if confidence clears threshold; no exact regex phrase |
| LLM | event=QZ991 payload=violet_ternary_oxide trace=7f2a91 | Groq is called when configured; otherwise unknown / llm_not_configured |

## Honest limitations

The CSV contains synthetic labeled examples for demonstration. This proves the model is trained and routing is implemented; it does not establish production accuracy. Evaluate on separate, real, de-identified logs before making accuracy claims. Regex rules require maintenance as log formats change.

Submitted log text is stored in local SQLite. Use synthetic or de-identified logs; this demo has no authentication and should not be exposed publicly with sensitive data.
