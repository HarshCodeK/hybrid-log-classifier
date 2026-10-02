---
kind: spec
title: "Limitations — what is broken, not merely unfinished"
comments: none
---

# Limitations

Grouped by whether they are **bugs** (something is wrong now) or **gaps**
(something is missing). The distinction matters: a bug is a defect I introduced,
a gap is a known boundary of the design.

---

## Bugs found and fixed during this rebuild

These were real defects, caught by running the code rather than reading it. Each
one *looked* like working code, which is why they are worth listing — they are
the argument for testing behaviour instead of trusting inspection.

### 1. Incident buckets keyed by entity set — data loss FATAL

```python
# Before: a dict keyed by the entity set
buckets = {}
...
buckets[grouping_key] = best_bucket   # ← overwrites silently
```

Two incidents on the same entity six hours apart **overwrote each other**. The
first incident's line count, timestamps and entities were gone; the second
inherited its key.

This is the worst class of bug in the whole project, because the symptom is
*missing data* rather than an error. The UI would show one incident where there
were two, and nothing would look wrong.

**Fixed** by indexing entity → *list* of candidate buckets and choosing by time
window. Regression test:
`test_same_entity_distant_in_time_splits`.

### 2. `note` defaulted to `None`, not `""` — whole-batch crash

```python
# Before
if row.get("note", "").startswith("LLM unavailable"):   # ← AttributeError
```

`dict.get(key, default)` only substitutes the default when the key is *absent*.
`classify_one` sets `"note": None` explicitly, so the key was present and
`.startswith()` was called on `None`.

**This crashed the entire batch on the first regex-tier line** — and the regex
tier fires on the majority of traffic. The old version of this project survived
only because its equivalent loop ran solely against LLM-tier lines.

**Fixed** with `(row.get("note") or "")`. Caught by the first real batch run.

### 3. `node-12` extracted as `12` — silent incident splitting

```python
# Before: the keyword "node" matched inside the hostname "node-12"
r"\b(?:host|node|server|instance)[- ]?([\w.-]+)"
```

The optional separator consumed the hyphen, so the capture group got `12`.
`node-12` and `db-12` became unrelated entities, and one host's logs split
across multiple incidents.

The hyphen is part of the *name*, not a separator between keyword and value.

**Fixed** with two alternatives: a keyword form requiring whitespace
(`server db-01`) and a prefix form keeping the whole token (`node-12`).
Regression tests: `test_extract_entities[...node-12...]`,
`test_same_host_different_phrase_still_matches`.

### 4. `api-gateway` matched both host and service — double registration

Adding `api-` to the host prefix list meant "service api-gateway" registered as
`host:api-gateway` **and** `service:api-gateway`. The inflated entity set split
incidents that should have merged.

**Fixed** by removing `api-` from the host prefixes — it is a service, and the
keyword `service` is explicit.

### 5. Wrong cost model after switching LLMs — silent misreporting

The cost table was two bare constants carrying Llama-3.3-70b's rates. When the
deployed model changed to `qwen/qwen3.8-27b`, those constants were never updated,
so **every reported cost was wrong by roughly 6×** and nothing failed.

This is the most embarrassing class of bug here, because the cost figure is the
single number this project exists to defend. A plausible-looking wrong number is
worse than no number.

**Fixed** by keying prices to model names, and by adding `tests/test_cost.py`
which asserts two differently-priced models produce different costs — the check
a bare-constant implementation cannot pass.

---

## Known gaps — boundaries of the current design

### The ML tier is not earning its place HIGH

Measured: **0.491** on held-out templates, accepting **3 of 53** lines at the
0.60 threshold. On the demo batch it fired **zero** times.

The honest reading: with 240 hand-written rows, the ML tier is a narrow filter
for Resource Usage lines, not a general classifier. It behaves correctly — it
abstains rather than guessing — but if the regex tier were removed the system
would work nearly as well.

**Why I kept it:** the routing architecture is the project's thesis, and the
threshold is a real, measured operating point rather than a guess. But I would
not claim the ML tier as a success, and I would not defend "it reduces LLM calls"
as a benefit on this dataset.

**What fixes it:** real log data. That is the binding constraint on every
accuracy number in this project.

### 240 training rows, 138 templates MED

The dataset is hand-written and small. `Unknown` recall is 0.118 and
`Deprecation Warning` is 0.200 — the model learned explicit failures and never
learned what normal looks like.

With public log datasets I could not map the labels onto my five operational
categories, which is why this is synthetic. **If asked: yes, it is small and
synthetic, and here is exactly what it costs and why.**

### Batch processing is serial MED

4,000 lines classify one at a time. The LLM tier is the bottleneck at ~200ms per
line, so a batch with 400 unmatched lines takes 80 seconds.

Concurrency would fix it. I did not build it because the LLM tier is 4% of
traffic on real batches, and parallelising it would complicate the routing logic
that this project is trying to make legible.

### No streaming MED

The whole batch returns at once. For a 4,000-line file that is several seconds of
a spinner. Progressive rendering is a UX nicety, not a correctness problem.

### No ground-truth feedback loop MED

When an operator disputes a classification, nothing captures it. Improving the
model requires me to notice a problem and hand-write more rows.

This is the gap I would fix first with more time, because it turns the system
from something that needs maintenance into something that improves by being used.

### No Docker LOW (but it is on my resume)

`requirements.txt` and a clean venv are the only setup path. Docker is listed on
my resume and there is no Dockerfile in this repository. **A genuine gap, not a
considered rejection** — see below.

### No CI MED

46 tests, no GitHub Actions workflow. They run locally in ~2 seconds. A workflow
would make them non-optional, which is what makes the documentation trustworthy.

The profile repository has CI; none of the project repositories do.

### Entity extraction is shallow MED

Four patterns: host, user, IP, service. Real logs carry request IDs, trace IDs,
HTTP status codes, pod names, database connection strings, and error codes — none
of which are extracted.

Consequence: lines are grouped by *human-readable* entities only. A burst of
errors sharing a trace ID but no username will not group.

---

## Not built, on purpose

| Not built | Why this is a decision, not an omission |
|---|---|
| Authentication | Single-user local tool bound to 127.0.0.1. Auth would imply a threat model that does not exist. If this ever listens on a network, auth is the first thing to add. |
| LangChain / LangGraph | The pipeline is 30 lines of `if`. A framework would obscure the one decision worth explaining. |
| Frontend framework | Eight components, one fetch. A build step and `node_modules` would add nothing. |
| PostgreSQL | No second user, no server to install. SQLite ships with Python. |
| ChromaDB | Nothing is retrieved or embedded here. It belongs in the financial assistant project, where it should be used properly rather than mentioned. |
| Fine-tuning | 240 rows cannot fine-tune anything. More data first. |
| Per-category metrics in the UI | Overall accuracy hides that Unknown and Deprecation Warning are where the model actually fails. **This one is worth doing** — it is a small change with real diagnostic value. |

---

## What I would do next, in order

1. **CI workflow** — makes the README-example tests authoritative, which
   prevents documentation drift permanently.
2. **Dockerfile** — a resume claim that is currently false.
3. **Real log data** — the binding constraint on every accuracy number here.
4. **Per-category metrics in the UI** — turns a vague "0.491" into a diagnosis.
5. **Ground-truth feedback loop** — the system improves by being used instead of
   by me hand-writing rows.

---

## The version of honesty I am aiming for

If you ask me what is wrong with this project, the answer should never be worse
than this document. The numbers in here are ones I measured on code I wrote, the
bugs are ones I actually introduced, and the ML tier being weak is stated before
anyone asks.

**The alternative — reporting that leaky 1.000 figure and hoping nobody holds
out whole templates — is how you get caught instead of being impressed.**
