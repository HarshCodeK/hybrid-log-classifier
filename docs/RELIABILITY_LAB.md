# Reliability lab

## What is measured

The API exposes \`GET /metrics\` with process-local request totals, currently active requests, server-error count, mean server-observed request duration, and route/status counts. Successful HTTP responses also include \`X-Process-Time-Ms\`.

These metrics are intentionally process-local. They reset on restart and are not aggregated across multiple workers or replicas. Do not interpret them as durable telemetry or as an estimate of real users.

## Repeatable load test

1. Train the model with \`PYTHONPATH=src python scripts/train.py\`.
2. Start the API using the repository's documented command.
3. Run \`PYTHONPATH=src python scripts/load_test.py --help\` to inspect supported options.
4. Start at low concurrency, then increase it in steps while keeping the same payload mix.
5. Record client p50/p95/p99 latency, requests/second, transport failures and HTTP status distribution alongside server metrics.
6. Repeat after a change and compare results under the same host, model artifact, request mix and test duration.

## Interpretation limits

A client-side load generator creates synthetic test traffic; it does not create product users. A result is valid only for the exact hardware, deployment tier, process count, persistence setup, payload mix and test duration recorded with it. No 10,000-concurrent-user claim is made by this repository alone.

SQLite and process-local metrics are single-host/demo choices. Multi-replica deployments need shared durable storage and aggregated telemetry.
