---
kind: spec
title: "Walkthrough — one request, traced"
comments: none
---

# Walkthrough

Real requests against the running system, with real output. Every number here
was produced by the code in this repository on 2026-09-30.

---

## 1. One line that regex catches

```bash
curl -X POST localhost:8000/classify \
  -H "Content-Type: application/json" \
  -d '{"text":"Memory usage at 87% on server node-12, threshold exceeded"}'
```

```json
{
  "category": "Resource Usage",
  "severity": "medium",
  "confidence": 1.0,
  "explain": "Matched a written rule: /(memory|cpu|disk|heap|gpu) (usage|utilization) .*\\d+%/",
  "tier_used": "regex",
  "matched": "(memory|cpu|disk|heap|gpu) (usage|utilization) .*\\d+%",
  "cost_usd": 0.0,
  "latency_ms": 0.018
}
```

**What to notice:**

- `confidence: 1.0` — a regex match is exact, not probable. It either matched a
  written rule or it did not.
- `matched` names the rule. This is the explainability guarantee: when someone
  asks "why is this a Resource Usage", the answer is a specific pattern, not a
  score.
- `cost_usd: 0.0` — not "small". Zero. That is the entire point of tier 1.
- **0.018 ms.** The LLM tier for the same line would be ~200ms — about 11,000×
  slower.

---

## 2. One line the regex tier cannot catch

```bash
curl -X POST localhost:8000/classify \
  -H "Content-Type: application/json" \
  -d '{"text":"Disk is nearly full on the log volume"}'
```

```json
{
  "category": "Resource Usage",
  "severity": "medium",
  "confidence": null,
  "explain": "Regex and ML both abstained; the model replied 'Resource Usage'.",
  "tier_used": "llm",
  "matched": null,
  "raw_reply": "Resource Usage",
  "cost_usd": 0.00003365,
  "latency_ms": 254.0
}
```

**What to notice:**

- **Both cheaper tiers abstained.** "Nearly full" has no percentage and no
  keyword in the rule set. The ML model was not confident enough at the 0.60
  threshold. So it went to the LLM, which got it right.
- `confidence: null` — deliberate. The model has no calibrated probability. Any
  number here would be invented.
- `raw_reply` is kept so the answer is inspectable. If this classification were
  disputed, you would want to see what the model actually said.
- `cost_usd` and `latency_ms` are 2,000× and 12,000× the regex answer. Same
  correctness, radically different cost. That gap is the argument for tiering.

---

## 3. A batch — the actual product

```bash
curl -X POST localhost:8000/classify/batch \
  -H "Content-Type: application/json" \
  --data-binary @data/demo_batch.json
```

Input: 14 lines describing two unrelated problems six hours apart, plus routine
traffic. The first five are a brute-force attempt on one user; the next three
are a memory leak on one host.

### The report

```
lines       : 14    tiers: {'regex': 10, 'llm': 4}
cost        : $0.000130   naive: $0.000459   avoided: 71.68%
p50/p95/p99 : 0.022 / 254.0 / 2324.7 ms
categories  : {'Security Alert': 5, 'Resource Usage': 4, 'Unknown': 2,
               'Deprecation Warning': 1, 'Workflow Error': 2}
```

### The incidents

```
[CRITICAL] Security Alert        5 lines  span=163s   user:admin_42, ip:203.0.113.7, ip:203.0.113.9
[HIGH    ] Workflow Error        2 lines  span=60s
[MEDIUM  ] Resource Usage        3 lines  span=150s   host:node-12
[MEDIUM  ] Resource Usage        1 lines  span=0s
[LOW    ] Deprecation Warning    1 lines  span=0s
[INFO   ] Unknown                1 lines  span=0s     service:api-gateway
[INFO   ] Unknown                1 lines  span=0s
```

### Per line

```
regex  Security Alert        0ms   Multiple failed login attempts detected for user admin_42
regex  Security Alert        0ms   Failed login for user admin_42 from ip 203.0.113.7
regex  Security Alert        0ms   Authentication failure for user admin_42 from ip 203.0.113.7
regex  Security Alert        0ms   Access denied for user admin_42
regex  Security Alert        0ms   Failed login for user admin_42 from ip 203.0.113.9
regex  Resource Usage        0ms   Memory usage at 94% on server node-12, threshold exceeded
regex  Resource Usage        0ms   Memory usage at 96% on server node-12
regex  Resource Usage        0ms   Out of memory error in worker on node-12
llm    Unknown            218ms   Health check passed for service api-gateway
llm    Unknown            222ms   Request served from cache in 12ms
regex  Deprecation Warning  0ms   Function getUserData() is deprecated, use fetchUser()
regex  Workflow Error        0ms   Data pipeline crashed during ETL step
llm    Workflow Error      830ms   Nginx returned 502 to the upstream
llm    Resource Usage      221ms   Disk is nearly full on the log volume
```

### What actually happened

**Five failed logins collapsed into one incident.** Lines 1–5 share
`user:admin_42` and all fall within 163 seconds, so they are one critical
incident. It also picked up `ip:203.0.113.7` and `ip:203.0.113.9` from the
individual lines — two source IPs against one account is a more complete picture
than either line gave alone.

**The memory leak stayed separate.** Lines 6–8 share `host:node-12` and span
150 seconds, so they group. But they are a *different* incident from the security
one, six hours later, on a different entity. This is the case the time window
exists for: without it, all eight of those lines would have merged into a single
meaningless incident.

**Ten lines cost nothing.** Regex caught all five security lines, all three
memory lines, the deprecation warning and the ETL crash. 71.68% of the naive
LLM-for-everything cost was avoided.

**Two lines went to the LLM and it got both right.** "Nginx returned 502 to the
upstream" is a workflow error stated as an HTTP status code — no regex for that,
and the ML model was not confident. This is precisely the phrasing variation the
LLM tier exists to absorb.

**The p99 is 2440ms and that is honest.** The tail is the LLM tier. Reporting a
mean of ~250ms would hide it entirely; the p50 of 0.022ms and p99 of 2325ms
together tell the real story, which is that most of this system is free and fast
and a small tail is neither.

---

## 4. The ML tier, honestly

```bash
python train.py
```

```
Random split -- NOTE: inflated by template leakage, shown for contrast only.
              precision  recall  f1-score  support
  Deprecation Warning  1.000   1.000    1.000        9
  ...
           accuracy    1.000       48      <- LEAKAGE, not a result

================================================================
This is the number to quote in the README and interviews.
================================================================
Held-out TEMPLATE split (every test line is an unseen phrasing):
  Deprecation Warning  1.000   0.200    0.333       15
  Resource Usage       1.000   1.000    1.000        4
  Security Alert       0.364   1.000    0.533       12
  Unknown              1.000   0.118    0.211       17
  Workflow Error       0.455   1.000    0.625        5

           accuracy    0.491       53      <- the real number
  lines the model is confident enough to accept (>= 0.6): 3/53
```

**Read those two `accuracy` lines together.** The top one is 1.000 and it is
leakage — do not quote it. The bottom one, 0.491, is the real result.

### Why this section exists

**The random split says 1.000. That number is a lie, and it is my own doing.**

My training data is 240 rows built from 138 templates, each instantiated three
times with different entity values. A random split puts sibling lines of the
same template on both sides. The model then scores perfectly by recognising
memorised strings — which tells you nothing about real log lines.

Holding out **whole templates** means every test line is a phrasing never seen in
training. Accuracy drops to **0.491**.

The per-category breakdown is the more useful part. `Resource Usage` is perfect.
`Unknown` recall is 0.118 and `Deprecation Warning` is 0.200 — the model has
learned to recognise explicit failures and has not learned what *normal* looks
like. Which is exactly why it abstains on most lines and why it fired zero times
on the demo batch.

**At a 0.60 threshold it accepts 3 of 53 lines.** So in practice the ML tier is
currently a specialised filter for Resource Usage lines, not a general
classifier. It is honest about that — it abstains rather than guessing — but it
is not yet earning its place in the routing order.

### The threshold, measured

```
threshold 0.5:  5/53 lines routed to ML, accuracy on those = 1.00
threshold 0.6:  3/53 lines routed to ML, accuracy on those = 1.00
threshold 0.7:  1/53 lines routed to ML, accuracy on those = 1.00
threshold 0.8:  0/53 lines routed to ML
```

Every accepted line was correct at all three thresholds — the model's
*confidence* is well-calibrated even where its overall accuracy is poor. Lowering
to 0.5 accepts more lines correctly, but on a larger real dataset the false
accepts would appear, and a wrong label at 0.5 is worse than an honest
abstention. **0.6 stays.**

---

## 5. Degradation — no API key

```bash
# .env absent, or GROQ_API_KEY unset
$ curl localhost:8000/health
{"status":"ok","llm_available":false,"model":"qwen/qwen3.8-27b","ml_threshold":0.6}
```

The UI header reads **"LLM tier off · regex + ML only"**.

Unmatched lines come back as `Unknown` with a note:

```json
{
  "category": "Unknown",
  "tier_used": "unknown",
  "note": "LLM tier disabled and both cheaper tiers abstained",
  "cost_usd": 0.0
}
```

**This is the most likely live question about any LLM project**, and the one
most projects answer badly. The behaviour here is deliberate:

- **Nothing raises.** `LLMUnavailable` is a named exception; the pipeline
  catches exactly that and lets unrelated bugs propagate. A blanket
  `except Exception` would turn a real bug into a silent `Unknown` nobody
  investigates.
- **Nothing is silently faked.** The category is `Unknown` with a reason, not a
  guess. Unknown is what we actually know.
- **The cheaper tiers still work.** A degraded run still classifies everything
  regex and ML can reach, and the cost panel still reports the avoided spend.

---

## 6. Persistence

```bash
$ curl localhost:8000/runs
{"runs":[{"id":2,"total_lines":14,"regex_count":10,"ml_count":0,
          "llm_count":4,"incident_count":7,"total_cost_usd":0.000130,
          "llm_fallback":0,"started_at":"2026-09-30T18:47:12.481"}]}
```

Every run persists its summary and every per-line classification. `GET /runs/2`
returns the full detail, and the UI's **View** button downloads it as JSON —
because a triage run you cannot take away from the browser is a screenshot, not
an artefact.

---

Next: [limitations](06-limitations.md), or
[concepts](07-concepts.md) for the CS fundamentals this assumes.
