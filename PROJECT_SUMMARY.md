# Hybrid Log Classifier — Project Summary

**Repository:** https://github.com/HarshCodeK/hybrid-log-classifier  
**Documentation snapshot:** 21 October 2026  
**Primary branch inspected:** `main` at `22aa49c878e4377f584801248d2469b7cb36cd6b`

This document explains the project, its implementation, model/data provenance, commands, tests, and the additional engineering work developed on other branches. It deliberately distinguishes what is in the current `main` snapshot from features that remain on other branch snapshots.

## 1. What the project does

Hybrid Log Classifier is a Python demo that triages application log text into ten operational categories. It uses a cost-conscious, explainable cascade:

1. **Regex rules** catch known high-signal log signatures.
2. **Local machine learning** uses TF-IDF features and Logistic Regression when no rule matches.
3. **Optional Groq-hosted LLM** is called when the ML score is below the configured threshold or the input has no terms in the learned vocabulary.
4. **Abstention (`unknown`)** is returned when the system cannot make a supported classification, or when the optional provider is unavailable/returns invalid output.

The main interfaces are a Streamlit demo and an optional FastAPI endpoint. Classification results and latency are saved to SQLite.

## 2. The ten trained categories

- `security` — authentication and access-control problems.
- `availability` — outages, failed health checks, or unavailable services.
- `performance` — latency, slow requests, and slow queries.
- `resource_exhaustion` — memory, disk, CPU, and other resource pressure.
- `database` — database connections, locks, transactions, and queries.
- `network` — DNS, TLS, sockets, routing, and packet delivery.
- `deployment` — rollout, release, container startup, and readiness failures.
- `data_integrity` — corruption, checksum, schema, or consistency problems.
- `configuration` — missing or invalid settings.
- `dependency_failure` — upstream services, caches, or brokers failing.

`unknown` is not an eleventh trained class. It means the system abstained instead of asserting an unsupported answer.

## 3. How the current-main classifier works

### Stage A — Regex

`hybrid_log_classifier/classifier.py` maintains case-insensitive regular expressions for the ten categories. It scans all rules, not just the first one. If one category matches, it returns that category and skips ML/LLM. If signatures from multiple categories match, it returns the distinct matched categories together. Repeated signatures for the same category are deduplicated.

### Stage B — TF-IDF + Logistic Regression

If no regex matches, the app transforms the text with scikit-learn's `TfidfVectorizer` using word unigrams and bigrams, lowercase normalization, and sublinear term frequency. A `LogisticRegression` model scores the ten categories.

The default threshold is `0.60`, configurable with `ML_CONFIDENCE_THRESHOLD`. A score at or above the threshold is accepted only if the input has terms in the fitted TF-IDF vocabulary. The score is a model score used for routing; it is **not** a measured accuracy figure or proof of calibration.

### Stage C — Optional Groq LLM

Groq is used only when enabled and a non-empty `GROQ_API_KEY` is present. The request uses the `GROQ_MODEL` setting (default in the current code: `openai/gpt-oss-20b`), temperature zero, JSON response mode, and an eight-second timeout. The log is truncated to 4,000 characters for the provider request. The response category, confidence range, and reason are validated. A provider error or invalid response produces an explicit abstention rather than a guessed category.

Logs are untrusted input. The system prompt tells the model to classify the log as data, not follow instructions embedded in it. This is a useful boundary, not a guarantee of complete prompt-injection protection.

## 4. Training data and model provenance

- **Dataset:** `data/training.csv`.
- **Source:** synthetic, hand-authored project examples; it is not a corpus of production logs.
- **Labels:** the ten categories listed above.
- **Training implementation:** `train_model()` in `hybrid_log_classifier/classifier.py`.
- **Minimum validation in code:** at least 100 non-empty examples, labels must cover exactly the ten supported categories, and text values must not be blank.
- **Model:** scikit-learn Pipeline: TF-IDF word unigrams/bigrams → Logistic Regression.
- **Pretrained model?** No. The local classifier is fitted from the included CSV when the classifier is instantiated. The current-main version does not check in a serialized model artifact, so a new process fits the model again.
- **External model:** the optional Groq model is a remote provider used only for fallback. It is separate from the local TF-IDF/Logistic Regression model.

**Important limitation:** synthetic examples are useful for a working demonstration and deterministic tests, but they cannot establish accuracy on real operational logs. Do not claim production accuracy, savings, or generalization without evaluation on representative, held-out real-world data.

## 5. Current-main file map

| Path | Purpose |
|---|---|
| `app.py` | Streamlit UI: accepts log text, invokes the classifier, displays category/stage/confidence/reason/latency, and persists the result. |
| `hybrid_log_classifier/classifier.py` | Category definitions, regex rules, dataset validation/training, ML threshold routing, Groq fallback, response validation, and result/latency construction. |
| `hybrid_log_classifier/api.py` | FastAPI app; `GET /health` and `POST /classify`; validates request length, caches classifier initialization, persists results, and returns structured JSON. |
| `hybrid_log_classifier/persistence.py` | Creates the SQLite table and writes log text, category, tier, confidence, latency, and timestamp. |
| `hybrid_log_classifier/__init__.py` | Package marker/docstring. |
| `data/training.csv` | Synthetic labeled training examples used to fit the local ML model. |
| `tests/test_app.py` | Tests training/category coverage, regex routing, multi-category results, threshold behavior, fallback, validation, and persistence/API behavior. |
| `requirements.txt` | Python runtime and test dependencies. |
| `.env.example` | Documents optional Groq key, model name, ML threshold, and database path without storing secrets. |
| `.gitignore` | Excludes local environment, bytecode, pytest cache, and runtime database files. |
| `.github/workflows/ci.yml` | GitHub Actions workflow that installs dependencies, compiles Python files, and runs pytest on pushes/PRs targeting `main`. |
| `PROMPT.md` | Repository-specific instructions for an AI coding assistant. It asks contributors to inspect code/tests first, make small tested changes, protect secrets, and avoid invented claims. |
| `README.md` | Public project overview, routing explanation, setup, examples, API usage, and limitations. |

## 6. Persistence and returned fields

The SQLite table is `classifications`. Each inserted row includes:

- `id` — auto-increment primary key.
- `log_text` — submitted log content.
- `category` — final category or `unknown`; for a multi-regex result, the current-main implementation joins categories into a string.
- `tier` — the stage/result path, such as `regex`, `ml`, `llm`, `llm_error`, or `llm_not_configured`.
- `confidence` — selected model score, rounded for output; regex matches use 1.0 as a deterministic rule-match marker, not a statistical probability.
- `latency_ms` — measured classification duration in milliseconds.
- `created_at` — SQLite timestamp.

The FastAPI response includes `category`, `categories`, `tier`, `confidence`, `reason`, and `latency_ms`. `POST /classify` accepts JSON with a `text` field (maximum 20,000 characters); blank text is rejected. `GET /health` is a simple liveness endpoint, not a deep readiness check.

**Privacy warning:** the database stores raw submitted log text. Use synthetic or de-identified logs; do not submit credentials, tokens, personal information, or sensitive production logs to this demo.

## 7. Setup and run on Windows

Open PowerShell in the repository root.

~~~powershell
python -m venv .venv
.\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\\.venv\\Scripts\\python.exe -m streamlit run app.py
~~~

Open the local URL printed by Streamlit, usually http://localhost:8501. Regex and ML work without a Groq key. To enable fallback, edit the local `.env` and set `GROQ_API_KEY=your_key_here`; never commit the real key. `GROQ_MODEL` can select a provider-supported model.

### Run the optional REST API

In a second PowerShell terminal, from the repository root:

~~~powershell
.\\.venv\\Scripts\\python.exe -m uvicorn hybrid_log_classifier.api:app --reload
~~~

- Health: http://127.0.0.1:8000/health
- Interactive API docs: http://127.0.0.1:8000/docs
- Classify endpoint: `POST http://127.0.0.1:8000/classify`

Example request JSON:

~~~json
{"text":"Database deadlock detected"}
~~~

The Streamlit UI does not require Uvicorn to be running.

### Run tests

~~~powershell
.\\.venv\\Scripts\\python.exe -m compileall -q hybrid_log_classifier app.py tests
.\\.venv\\Scripts\\python.exe -m pytest -q
~~~

GitHub Actions performs the same basic compilation and test steps. Tests mock Groq interactions where appropriate, so a real API key and provider credits should not be needed for the test suite.

## 8. Configuration reference

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` | Optional secret enabling Groq fallback. Keep it in local environment configuration; never commit it. |
| `GROQ_MODEL` | Groq-compatible model identifier. Current default: `openai/gpt-oss-20b`. |
| `ML_CONFIDENCE_THRESHOLD` | ML acceptance threshold, default `0.60`; must be greater than 0 and less than 1. |
| `DATABASE_PATH` | SQLite path; default `runtime/classifications.db`. |

## 9. Engineering changes captured in project history

The following work was also developed in this repository history and is important context when discussing the project:

- Improved confidence-based routing so the actual ML top score and threshold are explained before fallback.
- Added multi-category handling for logs that contain distinct regex signatures from multiple categories; duplicate category matches are deduplicated.
- Added tests for all ten regex categories, multiple simultaneous signatures, deterministic ML threshold behavior, provider fallback/failure, API validation, and SQLite persistence.
- Consolidated the GitHub Actions test workflow so the primary CI entry point installs dependencies, compiles source, and runs tests.
- Clarified the setup instructions, optional FastAPI/Uvicorn role, synthetic-data limitations, and the project analogy in the README.
- Added `PROMPT.md` so future AI-assisted changes are grounded in repository code and tests.

### Reliability/load-test engineering branch

GitHub PR #4 is recorded as merged, and the `reliability-final` branch retains a larger engineering version that includes process-local request metrics, API/provider request ceilings, SQLite WAL and retention behavior, a bounded load-test client, Docker/deployment configuration, and reliability/threat-model documentation. Its load test reports client-observed throughput, percentile latency, HTTP statuses, transport failures, and error rate. These are test measurements, not real-user or production-capacity claims.

### Bounded incident-triage branch

GitHub PR #5 is recorded as merged, and `agentic-incident-triage` retains a bounded incident-triage version. That implementation accepts a load-test report and log events, validates bounded inputs, classifies logs, groups events heuristically, correlates timestamped logs with the test window when possible, and drafts evidence-linked diagnostic checks. It is a fixed allowlisted workflow, not a free-form autonomous agent: it does not execute shell commands, change infrastructure, or prove root cause from aggregate metrics.

### Important branch-state discrepancy

The current `main` snapshot inspected for this document is a later, simplified code layout (`hybrid_log_classifier/` at repository root) and **does not contain the reliability/load-test and incident-triage files described above**. Comparing current `main` with the merge commits shows those files were subsequently removed from the main-tree snapshot. The richer versions remain available on `reliability-final` and `agentic-incident-triage`. Therefore, do not tell an interviewer that `/triage`, `/metrics`, `/ready`, the load-test scripts, Docker, or those reliability controls are active on current `main` without first re-integrating and retesting them.

- Current main: https://github.com/HarshCodeK/hybrid-log-classifier/tree/main
- Reliability branch: https://github.com/HarshCodeK/hybrid-log-classifier/tree/reliability-final
- Incident-triage branch: https://github.com/HarshCodeK/hybrid-log-classifier/tree/agentic-incident-triage
- PR #4: https://github.com/HarshCodeK/hybrid-log-classifier/pull/4
- PR #5: https://github.com/HarshCodeK/hybrid-log-classifier/pull/5

## 10. Limitations to state honestly

1. Training data is synthetic and small; real-world generalization is unproven.
2. Regex multi-label results work only when multiple maintained signatures match. ML and LLM fallback each return one category.
3. The ML confidence threshold is a routing rule, not a guarantee of correctness or calibration.
4. The LLM is optional and adds network latency, provider dependence, and possible cost.
5. `unknown` is an intentional safe outcome when evidence or fallback is insufficient.
6. SQLite is suitable for this demo but is not a distributed production database.
7. Current-main API has no user authentication. Do not expose it with sensitive logs or secrets.
8. Classification latency is measured locally; no benchmark or capacity result should be claimed unless measured under a documented workload.
9. A test passing proves the tested behavior, not production readiness.

## 11. Short interview explanation

> I built a hybrid log-triage system that uses deterministic regex rules for obvious signatures, then a local TF-IDF plus Logistic Regression model for wording variation, and escalates to a Groq LLM only when the local model cannot justify a classification. It supports ten operational categories, explicit abstention through `unknown`, optional FastAPI integration, a Streamlit demo, and SQLite history with per-classification latency. I added regression tests for routing, multi-issue signatures, confidence thresholds, fallback failure, API validation, and persistence. The included dataset is synthetic, so I present it as a working engineering prototype rather than claiming real-world accuracy or production readiness.

## 12. Fast navigation

- Main README: https://github.com/HarshCodeK/hybrid-log-classifier/blob/main/README.md
- AI coding prompt (root, uppercase filename): https://github.com/HarshCodeK/hybrid-log-classifier/blob/main/PROMPT.md
- Training data: https://github.com/HarshCodeK/hybrid-log-classifier/blob/main/data/training.csv
- Classifier implementation: https://github.com/HarshCodeK/hybrid-log-classifier/blob/main/hybrid_log_classifier/classifier.py
- Automated tests: https://github.com/HarshCodeK/hybrid-log-classifier/blob/main/tests/test_app.py
