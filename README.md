# Hybrid Log Classifier

A small incident-intelligence service that routes application logs through the cheapest trustworthy classifier first.

**Pipeline:** rules → local ML → optional LLM → unknown when the system cannot justify an answer.

**Stack:** Python, FastAPI, scikit-learn, Groq-compatible LLM API, SQLite, Streamlit.

## Why this project exists

Operational teams receive logs ranging from obvious events such as failed login to ambiguous wording such as the checkout path feels degraded. A single LLM call for every line is unnecessarily expensive and introduces a network dependency. A rules-only system cannot handle wording variation.

This project demonstrates an explicit decision boundary: deterministic evidence first, local statistical inference second, and a probabilistic model only when the cheaper tiers abstain. The ML tier is allowed to say “I do not know,” which makes escalation measurable instead of hiding uncertainty behind a forced prediction.

## Architecture

1. **Rules:** deterministic patterns handle narrow, high-confidence cases.
2. **Local ML:** character TF-IDF plus logistic regression handles wording variation and abstains below a configurable confidence threshold.
3. **Optional LLM:** Groq is called only after ML abstention. Provider responses are schema-validated; provider failures become unknown, not a fabricated classification.
4. **Persistence:** SQLite records classification outcomes and latency, retaining the newest 10,000 rows by default. WAL plus a busy timeout helps concurrent writes on one host; SQLite is not a multi-replica database. The stored row includes the submitted log text, so use synthetic/de-identified logs only and do not expose this unauthenticated demo to sensitive production logs.
5. **Interfaces:** FastAPI exposes the API, while Streamlit provides an interactive demo.

No vector database or orchestration framework is used because this problem does not require retrieval or complex workflow orchestration.

## Quickstart

Requires Python 3.11+.

~~~bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1
pip install -r requirements.txt
PYTHONPATH=src python scripts/train.py
PYTHONPATH=.:src pytest
PYTHONPATH=src python scripts/evaluate.py
PYTHONPATH=src uvicorn hybrid_log_classifier.api:app --reload
~~~

In another terminal, use PYTHONPATH=src streamlit run app.py for the UI.

Without GROQ_API_KEY, rules and ML still work. ML abstentions return unknown. The model is generated locally from the small included corpus; it is not production-trained.

## API

- GET /health: liveness only.
- GET /ready: initializes the classifier and checks readiness; use it for deployment health checks.
- GET /metrics: process-local request counters, status codes, in-flight count, and recent latency percentiles.
- POST /classify: accepts {"text": "failed login user=demo"} and returns category, tier, confidence, reason, and service-observed classification latency.
- GET /docs: interactive API documentation from FastAPI.

Example:

~~~bash
curl -s http://127.0.0.1:8000/classify \
  -H 'Content-Type: application/json' \
  -d '{"text":"failed login user=demo"}'
~~~

## Evaluation and honest interpretation

The included data is synthetic and small: 50 labeled examples across five categories. In the GitHub Actions evaluation run for commit `4eb0fe60a8ff0130ab86c8f3bb1175ca82385aa3` (Python 3.12; dependency versions resolved by CI at run time), grouped five-fold evaluation reported accuracy 0.580 and macro F1 0.539 over held-out examples. At confidence threshold 0.30, accepted coverage was 0.362, accepted accuracy 0.810, and accepted macro F1 0.727. These values are specific to that code/data/dependency run, not production claims; re-run `PYTHONPATH=src python scripts/evaluate.py` before publishing updated numbers after any change.

## Reproducible load testing

See docs/RELIABILITY_LAB.md. Start small and ramp:

~~~bash
python scripts/load_test.py --base-url http://127.0.0.1:8000 --requests 100 --concurrency 10 --output artifacts/load-10.json
curl http://127.0.0.1:8000/metrics
~~~

The report captures client-observed throughput, p50/p95/p99 latency, error rate, status codes, transport errors, and bytes received. It does not claim real users, server resource usage, or capacity beyond the tested host and workload. Keep both the first failing run and the retest after remediation.

## Deployment

The root render.yaml defines a free Render web service for the API. Free services sleep after inactivity and use ephemeral local storage, so this is a public demo, not 24/7 production hosting. Deploy the Streamlit UI separately through Streamlit Community Cloud using the root app.py entry point. The app bootstraps its small local model when the artifact is absent.

## Testing

CI trains the model, runs unit/API/service tests and grouped evaluation, compiles Python source, checks whitespace, builds the Docker image, starts it, checks health, and classifies a smoke-test log. Public CI avoids real provider calls, so tests do not require secrets or incur API cost.

## Security and limitations

Input lengths are bounded, provider output is validated, secrets come from environment variables, and the LLM prompt treats log text as untrusted data. These controls do not amount to complete prompt-injection protection.

Known limitations: synthetic and narrow training data; limited rules/entity coverage; SQLite intended for local or single-process use; no end-user authentication; heuristic incident grouping; optional provider availability and cost; and no production reliability claim. `/classify` has a shared process-local `API_REQUESTS_PER_MINUTE` cap (default 120/minute); when `GROQ_API_KEY` is configured, the effective cap is also limited by `LLM_REQUESTS_PER_MINUTE` (default 30/minute) to reduce accidental provider spend. This is not per-user or distributed rate limiting.

## License

MIT. See LICENSE.
