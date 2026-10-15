# Hybrid Log Classifier

A small incident-intelligence service that routes application logs through the cheapest trustworthy classifier first.

Pipeline: rules → local ML → optional LLM → unknown when the system cannot justify an answer.

Technology: Python, FastAPI, scikit-learn, Groq-compatible LLM API, SQLite, Streamlit.

## Why this project exists

Operational teams receive logs ranging from obvious events such as failed login to ambiguous wording such as the checkout path feels degraded. A single LLM call for every line is unnecessarily expensive and introduces a network dependency. A rules-only system cannot handle wording variation.

This project demonstrates a hybrid decision boundary: deterministic evidence first, local statistical inference second, and a paid probabilistic model only when the cheaper tiers abstain.

The key engineering idea is abstention. The ML tier is allowed to say “I do not know”. That makes escalation measurable instead of hiding uncertainty behind a forced prediction.

## Quickstart

Create a Python 3.11+ environment and install requirements.txt.

Run:

- PYTHONPATH=src python scripts/train.py
- PYTHONPATH=src pytest
- PYTHONPATH=src python scripts/evaluate.py
- PYTHONPATH=src uvicorn hybrid_log_classifier.api:app --reload

The API exposes GET /health, GET /metrics, and POST /classify. Responses other than /metrics include an X-Process-Time-Ms header. Metrics are process-local, reset on restart, and are not aggregated across workers. The Streamlit demo runs with PYTHONPATH=src streamlit run app.py.

The LLM is optional. Without GROQ_API_KEY, rule and ML paths still work; an ML abstention becomes unknown.

## Architecture decisions

1. Rules are first because explicit operational patterns are deterministic and cheap.
2. Character TF-IDF plus logistic regression is the local model because the corpus is small, log-like, and needs a probability signal for abstention.
3. SQLite is used for local history because there is no current multi-host database requirement.
4. No vector database is used because there is no retrieval problem.
5. No orchestration framework is used because the routing policy is a small explicit state machine.
6. The LLM is a last resort and its output is schema-validated.
7. Provider failure becomes unknown rather than a fabricated confident answer.

See docs/ARCHITECTURE.md for the full decision record and docs/RELIABILITY_LAB.md for the repeatable synthetic-load procedure, metric definitions, and capacity-claim limitations.

## Evaluation

The included dataset is synthetic and small. Its metrics are evidence about this repository's corpus, not production performance.

Current grouped five-fold evaluation:

- grouped accuracy: 0.489
- grouped macro F1: 0.422
- accepted coverage at confidence 0.30: 0.305
- accepted accuracy at confidence 0.30: 0.920
- accepted macro F1 at confidence 0.30: 0.873

The important trade-off is that the ML tier accepts roughly 30.5% of held-out examples at the configured threshold and is correct on roughly 92.0% of those accepted examples in this small evaluation. Remaining cases should escalate or remain unknown.

Regenerate the numbers after changing the data, model, features, or threshold. Do not present them as production benchmarks.

## Incident grouping

Events are grouped only when they share a supported entity, category, and bounded time window. This avoids turning every event mentioning the same host into one indefinite incident.

## Testing

The repository contains unit, integration, API, evaluation and build checks. Public CI trains the model, runs pytest, runs grouped evaluation, compiles sources, checks whitespace, builds the Docker image, starts the container, checks health, and classifies a smoke-test log.

A real Groq request is intentionally not part of public CI because it would require a secret and create a paid external test dependency. The provider boundary is tested with deterministic fakes. Live provider smoke testing belongs in a controlled environment.

## Security

Input lengths are bounded. Provider output is schema-validated. Provider failures fail closed. Secrets come from environment variables and are not written to SQLite. The LLM prompt treats log content as data.

These are application-level controls, not claims of complete prompt-injection protection or public-service hardening. See docs/THREAT_MODEL.md.

## Development history

The repository was reconstructed from the project concept only. The archived repository is preserved separately and is not part of this Git history.

The development history is intentionally small and phase-oriented:

- foundation
- domain and rules
- local ML
- routing and persistence
- incident grouping
- LLM fallback
- FastAPI
- Streamlit
- evaluation and interview documentation
- ML tuning
- CI, Docker and security audit

Each phase was tested before the next change was accepted.

## Interview preparation

docs/INTERVIEW_QA.md covers the main product, architecture, data, reliability, security, scale, testing and trade-off questions an interviewer can ask about the current implementation.

## Honest limitations

- training data is synthetic and small
- ML quality is not established on production logs
- rule and entity coverage is intentionally narrow
- SQLite is intended for local or single-process use
- there is no API authentication or rate limiting
- log text is untrusted and prompt injection is not fully solved
- incident grouping is heuristic

## License

MIT. See LICENSE.
