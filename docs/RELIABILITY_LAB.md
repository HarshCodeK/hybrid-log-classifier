# Reliability lab: reproduce failures, measure them, retest

This repository includes a client-side load probe and a process-local metrics endpoint. They measure different things: the probe measures the caller's HTTP experience; /metrics measures requests observed by this single application process.

## Start a local API

From the repository root:

~~~bash
PYTHONPATH=src python scripts/train.py
PYTHONPATH=src uvicorn hybrid_log_classifier.api:app --host 127.0.0.1 --port 8000
~~~

In a second terminal, start small and ramp gradually:

~~~bash
python scripts/load_test.py --base-url http://127.0.0.1:8000 --requests 100 --concurrency 10 --output artifacts/load-10.json
python scripts/load_test.py --base-url http://127.0.0.1:8000 --requests 500 --concurrency 25 --output artifacts/load-25.json
python scripts/load_test.py --base-url http://127.0.0.1:8000 --requests 1000 --concurrency 50 --output artifacts/load-50.json
curl http://127.0.0.1:8000/metrics
~~~

The JSON report includes request count, configured in-flight concurrency, throughput, p50/p95/p99/max latency, status codes, transport failures, and bytes received. /metrics includes per-route counters and percentiles over a bounded recent sample window. The generator uses a bounded worker pool, caps a run at 100,000 requests and 10,000 configured in-flight requests, and treats only 2xx responses as successful. These are safety bounds for the client, not a claim that the target can sustain that concurrency.

## What the evidence does and does not mean

- Concurrency 50 means up to 50 in-flight HTTP requests from this generator. It does not mean 50 human users, active accounts, or production sessions.
- A single run cannot establish capacity. Record the commit SHA, host/plan, region, cold versus warm state, request mix, concurrency, and test duration. Repeat each level at least three times.
- Record actual host CPU, memory, restarts, and logs separately. /metrics is process-local, resets on restart, and does not report CPU or memory.
- The training corpus is small and synthetic. Load results do not establish classifier accuracy or production-log quality.
- Test only services you own. Stop or reduce the run if it affects other users.

## Failure investigation checklist

1. Identify the first concurrency level where p95/p99 rises sharply or errors begin.
2. Correlate the load report with /metrics, process logs, CPU and memory from the host.
3. Classify the failure: validation (4xx), application exception (5xx), timeout/connection exhaustion, SQLite contention, provider error, or host restart.
4. Make one change at a time and rerun the same request mix and ramp. Keep both failed and retest JSON reports.
5. Explain the trade-off: e.g. waiting longer for SQLite writes can reduce transient lock errors but increase tail latency under sustained write pressure.

## Known limits and deployment notes

`/classify` applies a shared process-local ceiling of 120 requests/minute by default (`API_REQUESTS_PER_MINUTE`). When `GROQ_API_KEY` is set, the effective ceiling is also limited by `LLM_REQUESTS_PER_MINUTE` (default 30/minute). This reduces accidental resource/provider spend but limits all callers together; it is not authentication or distributed rate limiting. Test with the provider disabled and with a test key plus a low configured limit.

SQLite WAL is a single-host optimization, not a shared database for replicas. Free Render web services sleep after inactivity and use ephemeral local storage, so local records can disappear after restarts or spin-down. This is a portfolio/demo environment, not an uptime guarantee.

The /health endpoint is liveness. /ready initializes the model and reports readiness; use it for deployment health checks. /metrics is process-local and is not a production monitoring system.
