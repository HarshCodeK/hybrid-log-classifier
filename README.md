# Hybrid Log Classifier

A small incident-intelligence service that routes application logs through the cheapest trustworthy classifier first.

**Pipeline:** rules → local ML → optional LLM → `unknown` when the system cannot justify an answer.

**Stack:** Python 3.11+, FastAPI, scikit-learn, Groq-compatible LLM API, SQLite, Streamlit.

## Problem and design goal

Operational teams receive logs ranging from obvious events such as failed login to ambiguous wording such as a checkout path becoming degraded. Sending every line to an LLM adds cost and a network dependency; rules alone cannot cover every phrasing variation.

This project makes the decision boundary explicit: deterministic evidence first, a local statistical model second, and a remote model only when cheaper tiers abstain. The central idea is **abstention**: uncertainty should be visible and measurable instead of hidden behind a forced prediction.

## Architecture

`HTTP / Streamlit → input validation → rules → local ML → optional LLM → result + SQLite history`

- **Rules:** deterministic handling for supported operational patterns.
- **Local ML:** character TF-IDF features with logistic regression; a configurable confidence threshold allows abstention.
- **LLM fallback:** optional, schema-validated, bounded input; provider failure does not manufacture a confident label.
- **SQLite:** local classification history, not a distributed system of record.
- **FastAPI:** `GET /health` and `POST /classify`.
- **Streamlit:** demonstration interface.

See `docs/ARCHITECTURE.md` and `docs/THREAT_MODEL.md` for decisions and boundaries.

## Quickstart

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
PYTHONPATH=src python scripts/train.py
PYTHONPATH=src pytest
PYTHONPATH=src python scripts/evaluate.py
PYTHONPATH=src uvicorn hybrid_log_classifier.api:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/docs` for the API schema. In a second terminal, run the UI:

```bash
PYTHONPATH=src streamlit run app.py
```

The LLM is optional. Without `GROQ_API_KEY`, rule and ML paths still work; an ML abstention becomes `unknown`. Configuration includes `MODEL_PATH`, `DATABASE_PATH`, and `ML_CONFIDENCE_THRESHOLD`.

## Evaluation: what the numbers mean

The included dataset is synthetic and small. The current grouped five-fold evaluation reports:

| Metric | Result |
|---|---:|
| Grouped accuracy | 0.489 |
| Grouped macro F1 | 0.422 |
| Accepted coverage at confidence 0.30 | 0.305 |
| Accepted accuracy at confidence 0.30 | 0.920 |
| Accepted macro F1 at confidence 0.30 | 0.873 |

At this threshold, the ML tier accepts about 30.5% of held-out examples and is correct on about 92.0% of accepted examples in this specific evaluation. Coverage and accepted accuracy must be considered together: high selective accuracy is not useful if coverage is ignored.

These are **dataset evaluation results, not production accuracy or load-test results**. Regenerate them after changing data, features, model, or threshold. Do not claim 99% accuracy without a representative held-out corpus and a reproducible evaluation.

## Reliability, testing, and security

The repository includes unit, integration, API, evaluation, and build checks. CI trains the model, runs tests and grouped evaluation, compiles sources, checks whitespace, builds the Docker image, starts the container, checks health, and classifies a smoke-test log. A live Groq request is excluded from public CI because it needs a secret and creates an external cost dependency; the provider boundary is tested with deterministic fakes.

Input sizes are bounded, provider output is schema-validated, failures fail closed, and secrets are read from environment variables rather than written to SQLite. These are application-level controls, not complete prompt-injection protection or public-service hardening.

## Capacity and load testing

No concurrent-user capacity claim is made by this README. A credible benchmark must record the exact commit, host/plan, Python and dependency versions, dataset/model artifact, test duration, concurrency model, request mix, warm-up, and whether the LLM path is enabled.

For each run, measure throughput, p50/p95/p99 latency, HTTP error rate, timeouts, CPU/RAM, and classification outcomes by tier. Test health and classification endpoints separately; distinguish local rules/ML traffic from remote-LLM traffic because their bottlenecks and costs differ. Repeat the same workload after each mitigation and publish raw results plus the command used to reproduce them. Simulated clients are load-test traffic, not real users.

Likely first bottlenecks to investigate are synchronous request execution, SQLite write contention, model initialization, and provider latency/rate limits. These are hypotheses until measured. The current implementation has no API authentication or rate limiting and is not safe to expose as an unrestricted public service.

## Honest limitations

- Training data is synthetic and small; real-world generalization is unproven.
- Rule and entity coverage is intentionally narrow.
- SQLite is intended for local/single-process history; multi-instance deployment needs a different persistence design.
- There is no API authentication or rate limiting.
- Prompt injection through untrusted log text is not fully solved.
- Incident grouping is heuristic.
- No production availability, throughput, or maximum-concurrency guarantee is claimed.

## Interview preparation

`docs/INTERVIEW_QA.md` covers product fit, architecture, data leakage, abstention, reliability, security, scaling, testing, and trade-offs. Answers describe the current repository, not an idealized future version.

## License

MIT. See `LICENSE`.
