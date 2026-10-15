"""Repeatable HTTP load probe. Reports client-observed behavior only."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import sys
from time import perf_counter

import httpx

DEFAULT_PAYLOAD = {"text": "failed login user=load-test ip=203.0.113.10"}


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1))
    return round(ordered[index], 2)


async def run(args: argparse.Namespace) -> dict:
    base_url = args.base_url.rstrip("/")
    headers: dict[str, str] = {}
    for item in args.header:
        if "=" not in item:
            raise ValueError(f"invalid --header {item!r}; expected NAME=VALUE")
        name, value = item.split("=", 1)
        headers[name.strip()] = value

    if args.issue_api_key:
        admin_token = os.getenv(args.admin_token_env, "")
        if not admin_token:
            raise ValueError(f"set {args.admin_token_env} before using --issue-api-key")
        async with httpx.AsyncClient(timeout=args.timeout) as bootstrap:
            response = await bootstrap.post(
                f"{base_url}/v1/keys",
                headers={"X-Admin-Token": admin_token},
            )
            if response.is_error:
                raise RuntimeError(f"API-key bootstrap failed with HTTP {response.status_code}")
            key = response.json().get("api_key")
            if not key:
                raise RuntimeError("API-key endpoint returned no api_key")
            headers["X-API-Key"] = key

    payload = json.loads(args.payload) if args.payload else None
    limits = httpx.Limits(
        max_connections=args.concurrency,
        max_keepalive_connections=min(args.concurrency, 100),
    )
    latencies_ms: list[float] = []
    status_codes: dict[str, int] = {}
    transport_errors: dict[str, int] = {}
    response_bytes = 0
    success_count = 0
    error_count = 0
    semaphore = asyncio.Semaphore(args.concurrency)
    total_started = perf_counter()

    async with httpx.AsyncClient(timeout=args.timeout, limits=limits) as client:
        async def one_request() -> None:
            nonlocal response_bytes, success_count, error_count
            async with semaphore:
                started = perf_counter()
                try:
                    response = await client.request(
                        args.method,
                        f"{base_url}{args.path}",
                        headers=headers,
                        json=payload if args.method in {"POST", "PUT", "PATCH"} else None,
                    )
                    latencies_ms.append((perf_counter() - started) * 1000)
                    status = str(response.status_code)
                    status_codes[status] = status_codes.get(status, 0) + 1
                    response_bytes += len(response.content)
                    if response.status_code < 400:
                        success_count += 1
                    else:
                        error_count += 1
                except (httpx.HTTPError, OSError) as exc:
                    latencies_ms.append((perf_counter() - started) * 1000)
                    name = type(exc).__name__
                    transport_errors[name] = transport_errors.get(name, 0) + 1
                    error_count += 1

        await asyncio.gather(*(one_request() for _ in range(args.requests)))

    duration = max(perf_counter() - total_started, 1e-9)
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "client_python": platform.python_version(),
        "scope": "client-side HTTP behavior; no claim about server CPU or memory",
        "base_url": base_url,
        "method": args.method,
        "path": args.path,
        "requested_requests": args.requests,
        "configured_concurrency": args.concurrency,
        "duration_seconds": round(duration, 3),
        "throughput_requests_per_second": round(args.requests / duration, 2),
        "success_count": success_count,
        "error_count": error_count,
        "error_rate": round(error_count / args.requests, 5),
        "latency_ms": {
            "p50": percentile(latencies_ms, 0.50),
            "p95": percentile(latencies_ms, 0.95),
            "p99": percentile(latencies_ms, 0.99),
            "max": round(max(latencies_ms), 2) if latencies_ms else None,
        },
        "status_codes": status_codes,
        "transport_errors": transport_errors,
        "response_bytes_received": response_bytes,
        "notes": [
            "Concurrency means in-flight requests from this generator, not human users or sessions.",
            "Collect server CPU, memory, restarts and logs separately from the host.",
            "Record the commit, hosting plan, region, cold/warm state and request mix.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("BASE_URL", ""), help="service origin, e.g. http://127.0.0.1:8000")
    parser.add_argument("--path", default="/classify")
    parser.add_argument("--method", choices=["GET", "POST", "PUT", "PATCH"], default="POST")
    parser.add_argument("--payload", default=json.dumps(DEFAULT_PAYLOAD), help="JSON request body; ignored for GET")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--header", action="append", default=[], help="HTTP header as NAME=VALUE; may be repeated")
    parser.add_argument("--issue-api-key", action="store_true", help="issue a KAY-KAY key before the measured run")
    parser.add_argument("--admin-token-env", default="KAYKAY_ADMIN_TOKEN")
    parser.add_argument("--output", default="", help="optional path to save the JSON report")
    args = parser.parse_args()

    if not args.base_url:
        parser.error("pass --base-url or set BASE_URL")
    if args.requests < 1 or args.concurrency < 1 or args.timeout <= 0:
        parser.error("--requests, --concurrency and --timeout must be positive")
    if args.concurrency > 200:
        print("WARNING: high concurrency can overload a free instance. Cloudflare Quick Tunnels are documented for up to 200 in-flight requests.", file=sys.stderr)
    try:
        report = asyncio.run(run(args))
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        print(f"load test could not complete: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n", encoding="utf-8")
        print(f"Saved client-side report to {target}", file=sys.stderr)
    return 1 if report["error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
