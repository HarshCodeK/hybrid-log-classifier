# Hybrid Log Classifier

A small, explainable log-triage project. It classifies application logs into ten operational categories using **Regex → TF-IDF + Logistic Regression → optional Groq LLM**. The Streamlit UI and FastAPI endpoint use the same classifier, and classification results plus latency are stored in local SQLite.

## Ten alarm categories

security, availability, performance, resource_exhaustion, database, network, deployment, data_integrity, configuration, and dependency_failure.

unknown is an abstention when the system cannot classify responsibly; it is not an eleventh trained category.

## How the decision pipeline works

1. **Regex first:** high-precision known signatures are checked in order. A match returns immediately, so ML and the LLM are skipped.
2. **ML second:** if no rule matches, a scikit-learn Pipeline trained at startup from data/training.csv uses word/bigram TF-IDF and Logistic Regression. ML is accepted only when the log contains terms in the learned vocabulary and the top class probability meets ML_CONFIDENCE_THRESHOLD (default 0.45).
3. **Groq LLM last:** logs with no known vocabulary or a below-threshold ML result are escalated only if GROQ_API_KEY is configured. The prompt supplies the fixed category list and requires JSON with a category, confidence, and reason. The response is validated before use. If the key is missing, the response is invalid, or the request fails, the app returns an explicit unknown result rather than pretending classification succeeded.

The threshold is a routing heuristic for this demo, **not a calibrated probability or a measured accuracy guarantee**. The pipeline is designed to avoid LLM calls for recognizable logs; actual cost/latency savings have not been benchmarked here.

## Clone and set up (Windows PowerShell)

    git clone https://github.com/HarshCodeK/hybrid-log-classifier.git
    cd hybrid-log-classifier
    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    Copy-Item .env.example .env

Open .env and set GROQ_API_KEY= to your key if you want LLM escalation. Obtain a key from [Groq Console](https://console.groq.com/keys). Regex and ML still work without a key; uncertain logs return unknown. Never commit .env.

## Run the Streamlit interface

    .\.venv\Scripts\python.exe -m streamlit run app.py

Open the local URL Streamlit prints, usually http://localhost:8501. Paste a log and select **Classify log** to see the category, selected stage, confidence, latency, and reason.

## Run the FastAPI endpoint (optional)

The API is optional for using Streamlit. Uvicorn is included only as the ASGI server that runs FastAPI; it is runtime plumbing, not a separate classification layer.

    .\.venv\Scripts\python.exe -m uvicorn hybrid_log_classifier.api:app --reload

- Interactive API docs: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health
- Classify a log: send POST /classify with JSON such as {"text":"Database deadlock detected"}.

## Run tests

    .\.venv\Scripts\python.exe -m pytest -q

The tests cover training across all ten labels, every regex category, ML routing, mocked Groq escalation and failure behavior, API validation, and SQLite persistence. Groq calls are mocked in tests, so tests do not consume API credits.

## Test prompts

| Route | Prompt | Expected behavior |
|---|---|---|
| Regex → security | Failed login for user=alice from 203.0.113.8 | security / regex |
| Regex → availability | Health check failed for checkout service | availability / regex |
| Regex → performance | P95 latency spike exceeded alert limit | performance / regex |
| Regex → resources | OOMKilled: container exceeded memory limit | resource_exhaustion / regex |
| Regex → database | Database deadlock detected while committing transaction | database / regex |
| Regex → network | DNS resolution failed for api.internal | network / regex |
| Regex → deployment | Rollout failed for payments release | deployment / regex |
| Regex → integrity | Checksum mismatch detected for stored object | data_integrity / regex |
| Regex → configuration | Missing environment variable PAYMENT_SECRET | configuration / regex |
| Regex → dependency | Circuit breaker opened after upstream dependency failures | dependency_failure / regex |
| ML | The endpoint response time became sluggish during peak traffic | ML may select performance if vocabulary and threshold permit it; otherwise it escalates |
| LLM | qzxvblorf=99173 glarfnok_tesselate=0xA9 | Calls Groq when configured; otherwise returns unknown / llm_not_configured |

## Why these technologies

- **Python:** application logic and orchestration.
- **scikit-learn:** train and run the TF-IDF + Logistic Regression classifier.
- **Groq:** optional hosted LLM fallback for uncertain or unfamiliar logs.
- **FastAPI:** expose classification as a REST endpoint.
- **Streamlit:** provide a small interactive UI.
- **SQLite:** persist the input log, predicted category, selected tier, confidence, latency, and timestamp.
- **Uvicorn:** serves the FastAPI app during API demonstrations; it is not another classifier or a separate resume skill claim.

These are the technologies actually used by the implementation. No clustering layer or separate vector database is needed for this project's current scope.

## A note on TypeSafe AI's Jev

TypeSafe AI describes [System One models and Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) as being designed for fast, structured decisions that software can consume, including typed outputs and explicit uncertainty.

This project uses a **related architectural principle, not Jev itself**: each stage has a defined role, categories are fixed in advance, confidence influences routing, and the LLM response is validated before the application accepts it. The current Groq integration is still a conventional text-generating LLM that returns JSON; it does **not** provide Jev's model architecture or guarantees. The ML confidence in this project is also not calibrated, and JSON validation cannot guarantee that a category is factually correct.

## Limitations

The CSV contains synthetic labeled examples for demonstration. This proves the model is trained and routing is implemented; it does not establish production accuracy. Evaluate on separate, representative, de-identified logs before making accuracy claims. Regex rules need maintenance as log formats change.

Submitted log text is stored in local SQLite. Use synthetic or de-identified logs; this demo has no authentication and should not be exposed publicly with sensitive data.
