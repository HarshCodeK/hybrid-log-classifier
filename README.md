# Hybrid Log Classifier

A Python log-triage project that classifies application logs into ten operational categories. The pipeline is Regex → TF-IDF + Logistic Regression → optional Groq LLM. Results and measured latency are stored in SQLite.

## What it does

- Streamlit provides the interface for pasting a log and seeing its category, route, confidence, reason, and latency.
- Regex catches known log signatures first. If signatures from multiple categories appear, it returns each matching category.
- If no regex signature matches, a scikit-learn model scores the log using patterns learned from labeled examples.
- When the ML score is below 60%, or the text has no terms in the model's vocabulary, the app can ask Groq to classify it. This fallback only runs when GROQ_API_KEY is configured.
- FastAPI exposes the same classifier as an optional REST endpoint. You do not need to start it to run the Streamlit demo.

The training CSV is synthetic and intended for a project demo. This is not a production-validated classifier, and no real-world accuracy or cost savings are claimed.

## The ten categories

| Category | Meaning | Example |
|---|---|---|
| security | Authentication or access-control problems | Failed login |
| availability | Service down or health check failure | Health check failed |
| performance | Slow requests or high latency | P95 latency spike |
| resource_exhaustion | Memory, disk, CPU, or other resource pressure | Disk space is full |
| database | Database connection, query, lock, or transaction issues | Database deadlock |
| network | DNS, TLS, socket, routing, or packet delivery problems | DNS resolution failed |
| deployment | Release, rollout, container startup, or readiness problems | Rollout failed |
| data_integrity | Corrupt data, checksum, schema, or consistency problems | Checksum mismatch |
| configuration | Missing or invalid settings | Missing environment variable |
| dependency_failure | An external service, cache, or broker is failing | Circuit breaker opened |

unknown is an abstention when the app cannot make a supported classification. It is not an eleventh trained category.

## How routing works

1. Regex checks every maintained signature. One matching category returns one category; signatures from two different categories return both. ML and Groq are skipped when regex matches.
2. If no regex matches, TF-IDF transforms the text into word and adjacent two-word features. Logistic Regression scores the ten trained categories.
3. ML is accepted only if the text contains terms from the learned vocabulary and its highest score is at least 0.60 by default.
4. If the ML score is below 0.60, the app explains the actual top score and why it is escalating. If there are no learned terms, the app explains that instead. Groq is called only if GROQ_API_KEY is configured.
5. If Groq is not configured, fails, or returns invalid output, the result is unknown rather than a fabricated classification.

The 0.60 threshold is a routing setting, not a calibrated probability or a claim that the model is 60% accurate. Set ML_CONFIDENCE_THRESHOLD in .env to change it.

## Examples to try

| Route | Paste this log | Expected behavior |
|---|---|---|
| Regex — security | Failed login for user=alice from 203.0.113.8 | security / regex |
| Regex — availability | Health check failed for checkout service | availability / regex |
| Regex — performance | P95 latency spike exceeded alert limit | performance / regex |
| Regex — resources | OOMKilled: container exceeded memory limit | resource_exhaustion / regex |
| Regex — database | Database deadlock detected while committing transaction | database / regex |
| Regex — network | DNS resolution failed for api.internal | network / regex |
| Regex — deployment | Rollout failed for payments release | deployment / regex |
| Regex — integrity | Checksum mismatch detected for stored object | data_integrity / regex |
| Regex — configuration | Missing environment variable PAYMENT_SECRET | configuration / regex |
| Regex — dependency | Circuit breaker opened after upstream dependency failures | dependency_failure / regex |
| ML | The endpoint response time became sluggish under load | No regex signature; the real model should choose ML only if its top score reaches 60%. |
| LLM fallback | qzxvblorf=99173 glarfnok_tesselate=0xA9 | Groq is tried if configured; otherwise the result is unknown. |
| Two issues | Database connection timed out; disk space is full on worker-3 | resource_exhaustion and database / regex |
| No useful vocabulary | qzxvblorf=99173 glarfnok_tesselate=0xA9 | Groq fallback if configured; otherwise unknown |

The two-issue behavior is signature-based. The regex stage scans all ten rules and collects distinct matches. ML and LLM fallback still produce one category each; semantic multi-label prediction without matching regex signatures is not implemented.

## How the ML model is trained

There is a real ML model in this project. It is not a pretrained model downloaded from the internet, and you do not need to train it manually.

- Training data: data/training.csv, a small synthetic labeled dataset covering the ten categories.
- Model: scikit-learn Pipeline with TfidfVectorizer using word unigrams and bigrams, followed by LogisticRegression.
- Training: train_model() reads the CSV and calls fit() when the classifier is first created.
- Model file: no saved model file is checked in. The fitted model lives in memory while the Streamlit or API process runs; a new process trains it again from the CSV.
- Why use ML: regex rules are clear and fast but depend on known phrases. TF-IDF plus Logistic Regression can recognize related word combinations even when the exact regex phrase is absent, without requiring a large neural model.
- Limitation: training successfully does not prove accuracy. The dataset is synthetic, and the model has not been validated on a representative real-world log dataset.

The app shows the selected stage and confidence. When the model has learned terms but its top score is below 60%, the result reason includes that exact ML score and threshold before the Groq response. If no learned terms are present, the reason says so instead.

## Run it on Windows

From PowerShell in the project directory:

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    Copy-Item .env.example .env
    .\.venv\Scripts\python.exe -m streamlit run app.py

Open the local URL printed by Streamlit, usually http://localhost:8501. You can use Regex and ML without a Groq key. To enable the LLM fallback, put your key in the local .env file as GROQ_API_KEY=your_key_here and restart the app.

## Why FastAPI and Uvicorn are here

FastAPI exposes the classifier so another program can send a log in an HTTP request and receive a structured JSON result. It is useful when integrating the classifier with another service; it is not required by the Streamlit interface.

Uvicorn is the ASGI server that runs the FastAPI application. It does not classify logs itself. Keep the API because it provides a useful way to demonstrate the same classifier through a REST endpoint; only start it when you want to demo that integration.

    .\.venv\Scripts\python.exe -m uvicorn hybrid_log_classifier.api:app --reload

Then open http://127.0.0.1:8000/docs. Example POST /classify body:

    {"text":"Database deadlock detected"}

The response contains category, categories, tier, confidence, reason, and latency_ms. The categories array supports the multiple-regex-match case. Streamlit works without Uvicorn.

## Run the tests

    .\.venv\Scripts\python.exe -m pytest -q

The tests cover each regex category, multi-issue routing, real model training, ML threshold routing, Groq fallback and failures, API validation, and SQLite persistence. Groq requests are mocked in tests so no API key or API credits are needed.

## Main files

- hybrid_log_classifier/classifier.py — regex signatures, model training, routing, and Groq fallback.
- data/training.csv — labeled training examples.
- app.py — Streamlit interface.
- hybrid_log_classifier/api.py — optional REST API.
- hybrid_log_classifier/persistence.py — SQLite writes.
- tests/test_app.py — automated tests.

## Project assistant prompt

PROMPT.md contains a short prompt for an AI coding assistant to inspect the code first, explain actual behavior, make small tested changes, and avoid claiming features or results that are not implemented.
