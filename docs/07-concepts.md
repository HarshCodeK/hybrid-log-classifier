---
kind: spec
title: "Concepts — the fundamentals this assumes"
comments: none
---

# Concepts

What this project assumes you already know, and — more usefully — where a
reviewer might reasonably say you do not.

Written as "you need this because line N depends on it", not as a CS tutorial.

---

## Concepts you must have

### Regex alternation and capture groups

`config.py` is the most regex-dense file in the project, and the reason is
legibility: one pattern per line, each with a comment, rather than ten
alternatives crammed into one string.

```python
_c(r"(memory|cpu|disk|heap|gpu) (usage|utilization) .*\d+%")
```

Three things to be able to say about that line:

- `(a|b|c)` is alternation — any one of these.
- `\d` is a character class for digits. `.*` is greedy any-character.
- `re.IGNORECASE` is applied once in `_c()` rather than repeated per pattern, so
  no individual rule can forget it.

**Why it matters here:** the previous version of this project packed five
patterns onto one line per category. A typo in any one of them was nearly
impossible to find, and a reviewer could not review it.

### Ordered dict iteration and rule precedence

```python
for category, patterns in REGEX_PATTERNS.items():
    for pattern in patterns:
        if pattern.search(text):
            return category        # first match wins
```

Python dicts preserve insertion order. That is load-bearing, not incidental:
`Security Alert` is listed before `Resource Usage`, so a line matching both
("blocked due to high memory") is filed as a security event.

**The question to expect:** *"what if the order is wrong?"* The honest answer is
that specific-first ordering is a judgement call encoded in a literal list, it is
not tested for correctness against real traffic, and "blocked" in
`Security Alert` is deliberately late in the list because it also appears in
resource errors. `T8. README contradicts itself` in the original repo is what
happens when this kind of precedence is undocumented.

### Truthiness and the `or` idiom

```python
value = next((g for g in match.groups() if g), None)     # first non-empty group
(row.get("note") or "").startswith(...)                   # None-safe
```

The host regex has two capture groups because it has two alternatives. `group(1)`
alone would silently ignore every match from the second form. `lastindex` is not
sufficient either — it reports the last *participating* group, not the first
populated one.

**Why it matters:** this is the difference between extracting `node-12` and
extracting `12`, and it silently split incidents until a test caught it.

### Float comparison and the confidence threshold

```python
if confidence >= ML_CONFIDENCE_THRESHOLD:   # 0.60
```

Never `if confidence == 0.6`. Floating point means the value that "should" be
0.6 is usually 0.5999999999999999 or 0.6000000000000001. This is why the threshold
is a named constant rather than a literal repeated in three places.

### `dict.get(key, default)` vs `dict.get(key) or default`

This distinction caused a real crash:

```python
row.get("note", "")      # returns None if the key exists with value None
(row.get("note") or "")  # returns "" for both missing AND None
```

`get` with a default only substitutes when the key is **absent**. When the key is
present and set to `None`, you get `None` back. This is a subtle, extremely
common Python bug.

---

## Concepts the project measures, not just uses

### Data leakage in train/test splits

**The most important idea in this repository.**

My training data is 240 rows built from 138 templates, each instantiated three
times:

```
"Memory usage at 87% on server node-12"
"Memory usage at 94% on server node-12"
"Memory usage at 91% on server node-12"
```

These three are *siblings*. A random train/test split scatters them across both
sides, so the test set contains near-copies of training data. The model scores:

```
random split        →  1.000 accuracy   <- leakage
template-grouped    →  0.491 accuracy   <- the real number
```

**The 1.000 line is leakage and must never be quoted.** It is shown here only so
the contrast is visible.

**The general rule: your split must reflect the question you are asking.** If you
care about performance on *novel phrasings*, then whole phrasings must be held
out. Holding out random rows from a set of near-duplicates measures memorisation.

```python
splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
train_idx, test_idx = next(splitter.split(X, y, groups=groups))
```

**Why this is the single best thing to understand from this project:** anyone can
check your accuracy number in ten lines. Being the person who says *"my random
split reports 1.0, but that's leakage — hold out whole templates and it's 0.49"*
is a far stronger position than being found out.

### Stratified splits

```python
train_test_split(..., test_size=0.2, random_state=42, stratify=y)
```

Without `stratify`, a small class can end up with zero test examples, making the
report silently wrong — you get a beautiful precision score for a class that was
never actually tested.

`random_state=42` for a different reason: without it, the reported score changes
every run and you cannot distinguish an improvement from a reshuffle.

### Precision and recall, and why overall accuracy lies here

From `train.py`, held-out templates:

| Class | Precision | Recall | What it means |
|---|---|---|---|
| Resource Usage | 1.000 | 1.000 | reliable both ways |
| Unknown | 1.000 | **0.118** | when it says Unknown, it is right — but it misses 88% of them |
| Deprecation Warning | 1.000 | **0.200** | same shape |
| Security Alert | **0.364** | 1.000 | catches them all, but flags a lot of false alarms |
| **Overall** | | **0.491** | |

High precision + low recall means the model is *conservative*: it only claims a
category when the signal is clear. For an operations tool that is the correct
failure mode — a missed deprecation warning is noise, whereas a false security
alert is a false alarm at 2am.

**Accuracy of 0.491 with precision 1.0 on three classes is a very different
system from accuracy 0.491 with precision 0.3 everywhere.** The number alone
tells you almost nothing.

### Confidence calibration

`predict_proba` returns a distribution; the threshold decides when to trust it.

```
threshold 0.5:   5/53 lines accepted, accuracy 1.00
threshold 0.6:   3/53 lines accepted, accuracy 1.00
threshold 0.8:   0/53 lines accepted
```

Every accepted line was **correct at every threshold**. The model's confidence is
well-calibrated even where its accuracy is poor — it is unsure exactly where it
is unsure.

That is what makes thresholding a defensible engineering decision rather than a
guess: you can measure whether raising it buys precision, and here it does,
because the model abstains rather than guesses when wrong.

---

## Concepts specific to this design

### Cascading / tiered classification, and why abstention is a feature

The architecture is a cascade: each tier may return "no answer", and the request
falls through to the next.

The design principle is that **abstention must be a first-class outcome**. If a
tier always guesses, you cannot tell which answers were earned, and the cost
panel becomes meaningless.

Contrast with the anti-pattern: a tier that returns its best guess with 0.31
confidence. That number would route into a decision, and nobody would notice.

### Entity-based grouping vs. pure time-window grouping

Two conditions, both required:

```
same incident  ⇔  shares ≥1 entity  AND  within 300 seconds
```

- **Entity alone:** every `db-01` timeout across a week merges into one endless
  incident.
- **Time alone:** unrelated errors that coincidentally happened together merge.

Together they mean "the same thing, happening now".

**Why the window is per-bucket, not global:** incidents in different parts of a
file must not merge merely because they are near each other. The comparison is
against each bucket's own `last_seen`, not against the newest line overall.

### Why Unknown is a real category

A health check passing is not an alert. A model forced into five buckets where
one is `Unknown`, but never told `Unknown` is legitimate, will invent alerts.

This is why `SEVERITY[UNKNOWN] = "info"` exists rather than the lines being
dropped — silently discarding unrecognised log lines would be the dangerous
choice for an operations tool.

### Graceful degradation as a design goal

The system has a defined behaviour at every level of LLM availability:

| Condition | Behaviour |
|---|---|
| Key present, model healthy | Full three-tier routing |
| Key present, model retired | `LLMUnavailable` → Unknown with reason, batch completes |
| Key absent | `llm_available: false` in `/health`, UI shows "regex + ML only" |
| `groq` not installed | Same as absent key — the import is optional |
| Network down | Same — provider exceptions are caught by type |

The key distinction: `LLMUnavailable` is a **named** exception, and the pipeline
catches exactly that. A blanket `except Exception` would also swallow real bugs
and report them as `Unknown` — which is how a genuine defect becomes invisible.

---

## Where you could reasonably be challenged

Honest weak spots, so you are not surprised:

| Challenge | Honest answer |
|---|---|
| *"Your entity extraction is four regexes. Isn't that brittle?"* | Yes. It misses trace IDs, request IDs, error codes. It groups by human-readable entities only. |
| *"0.491 accuracy — why ship that?"* | Because the tier abstains rather than guessing, so it cannot make things worse. But it is not earning its place yet, and real data is the fix. |
| *"Isn't regex ordering fragile?"* | Yes, and it is a judgement call in a literal list. "blocked" is deliberately late because it also appears in resource errors. |
| *"Your cost estimates are character-based."* | Correct — ~4 chars/token plus a measured prompt. Order-of-magnitude only, not billing reconciliation. |
| *"Why not just use the LLM?"* | 100× the cost, ~12,000× the latency on 71% of traffic, and it cannot tell you which rule fired. |
| *"Why SQLite?"* | Single-user local tool, no server to install. First concurrent user changes the answer. |
