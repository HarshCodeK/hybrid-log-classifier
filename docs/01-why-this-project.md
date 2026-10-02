---
kind: spec
title: "Why this project exists"
comments: none
---

# Why this project exists

## The problem

An on-call engineer gets paged at 2am. Their service has been throwing errors
for twenty minutes. They open the log viewer and find **4,000 lines** where
there used to be 200.

Nobody reads 4,000 lines. That is the actual problem, and it is not an AI
problem. It is a "too much signal, not enough triage" problem.

The tools that exist assume you will read them. Splunk charges per gigabyte and
still hands you a search bar. A regex grep tells you a line matched but not
whether it matters. An LLM that reads all 4,000 lines tells you something, but
costs real money at real latency — and 95% of those lines were never going to be
interesting.

## What I built

**An Incident Triage Console.** Paste or drop a log file. Get back a short,
ranked list of incidents with severity, first/last seen, affected entities, and
example lines — plus a downloadable report and the cost of the run.

The demo batch (14 lines, `data/demo_batch.json`) produces:

```
7 incidents
  [CRITICAL] Security Alert        5 lines  span=163s   user:admin_42, ip:203.0.113.7, ip:203.0.113.9
  [HIGH    ] Workflow Error        2 lines  span=60s
  [MEDIUM  ] Resource Usage        3 lines  span=150s   host:node-12
  ...
14 lines → 10 by regex (free), 4 by LLM
$0.000130 spent vs $0.000459 if everything went to the LLM — 71.68% avoided
p50 latency 0.022ms, p95 254ms
```

Five failed logins for the same user collapse into one critical incident. The
memory warnings six hours later on a different host stay separate, because they
are a different problem.

## The idea underneath it

> **Use intelligence only where intelligence is needed.**

Most log lines are formulaic. "Memory usage at 94%" means the same thing every
time and needs no model to recognise. Paying to run an LLM on it would be paying
for something we already knew.

So the system tries cheap methods first and only escalates when the cheap ones
say "I don't know":

```
log line
   │
   ▼
regex      ── matched?  ──────────────► done. free, microseconds.
   │ no
   ▼
ML model   ── ≥0.60 confident? ───────► done. free, milliseconds.
   │ unsure
   ▼
LLM        ──────────────────────────► done. ~$0.00003, ~200ms.
```

On the demo batch that is **10 of 14 lines answered for free**.

## Why three tiers and not one

I built the regex-only version first, then added ML, then added the LLM. Each
tier exists because the one below it had a specific, observed failure:

| Tier | Exists because | Cost | Latency | Accuracy |
|---|---|---|---|---|
| **Regex** | Log lines follow templates | free | ~0.02ms | 100% when it fires, 0% when it doesn't |
| **ML (TF-IDF + logistic regression)** | "disk is nearly full" says the same thing as "disk space at 94%" with no rule written for it | free | ~1ms | **0.491** on unseen phrasings |
| **LLM** | Genuinely unfamiliar wording | ~$0.00003 | ~200ms | **15/15** on the held-out set |

An LLM-only version would have been simpler to write and easier to demo. It also
costs 100× more and is 10,000× slower on the majority of traffic, and it cannot
explain itself — a regex match tells you *which rule fired*, which is something
you can show an on-call engineer.

## What I rejected

**An LLM for everything.** Simplest to build. Rejected because cost and latency
scale linearly with log volume, and log volume is the one thing you cannot
control on an incident page.

**Regex only.** Genuinely free and genuinely fast. Rejected because it abstains
constantly on real phrasing, and an "Unknown" bucket containing every problem
is worse than no tool at all.

**A fine-tuned classifier.** Would probably beat TF-IDF on accuracy. Rejected at
this scale: 240 labelled rows is not enough data to fine-tune anything, and a
fine-tuning pipeline is a lot of machinery for a five-way choice that a linear
model handles.

**LangChain / LangGraph.** The whole pipeline is 30 lines of `if` statements. A
framework would add a dependency, a learning curve, and indirection between me
and the thing I am trying to explain in an interview.

## The honest part

**The ML tier is the weak link, and I measured how weak.**

```
Random train/test split:          1.000 accuracy   <- misleading
Template-grouped split:           0.491 accuracy   <- the real number
```

The 1.000 is leakage. My training data is 240 rows built from 138 templates,
each instantiated three times with different values. A random split puts
sibling lines of the same template on both sides, so the model recognises
memorised strings rather than learning the task. Holding out whole templates —
so every test line is a phrasing never seen in training — drops it to 0.491.

`train.py` prints both numbers and labels the flattering one as leakage, because
a model that reports only the flattering number is worse than no model. You
should expect me to quote 0.491, not 1.000.

**What that means in practice:** at the 0.60 threshold, the ML tier accepts
between 3 and 5 lines out of 53 on unseen phrasing. On the demo batch it fired
**zero** times — everything either matched regex or went to the LLM. The tier is
correct, but with 240 rows it is not earning its place yet.

## What I would fix next, in order

1. **Get real log data.** 240 hand-written rows is the binding constraint on
   every number in this project. A public dataset with real phrasing would fix
   the ML tier and possibly remove the LLM tier's need for low-confidence cases.
2. **Per-category precision/recall in the UI.** Overall accuracy hides that
   "Deprecation Warning" and "Unknown" are where the model actually struggles.
3. **Ground-truth feedback loop.** When an operator corrects a classification,
   log it and add it to the training set. Right now improvements require me to
   notice a problem and hand-write more rows.
4. **Streaming for large files.** 4,000 lines currently classify serially. The
   LLM calls are the bottleneck and could be batched or run concurrently.

See [limitations](06-limitations.md) for what is broken rather than merely
unfinished, and [tech-stack](03-tech-stack.md) for why each library is here.
