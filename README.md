# Incident Triage Console

**14 log lines in, 7 ranked incidents out.** An on-call engineer at 2am does not
need 4,000 log lines classified. They need to know which six things are on fire
and what to fix first.

Paste a log file. Get a severity-ranked incident list, the cost of the run, and
a downloadable report.

```
7 incidents
  [CRITICAL] Security Alert     5 lines  span=163s   user:admin_42, ip:203.0.113.7, ip:203.0.113.9
  [HIGH    ] Workflow Error     2 lines  span=60s
  [MEDIUM  ] Resource Usage     3 lines  span=150s   host:node-12
  ...

14 lines → 10 by regex (free), 4 by LLM
$0.000130 spent vs $0.000459 if everything went to the LLM — 71.68% avoided
p50 latency 0.022ms, p95 254ms
```

---

## The idea

**Use intelligence only where intelligence is needed.**

Most log lines are formulaic. "Memory usage at 94%" means the same thing every
time and needs no model to recognise. Paying to run an LLM on it would be paying
for something we already knew.

```
log line
   │
   ▼
regex      ── matched?  ──────────────► done.  free, 0.02ms
   │ no
   ▼
ML model   ── ≥0.60 confident? ───────► done.  free, 1ms
   │ unsure
   ▼
LLM        ──────────────────────────► done.  ~$0.00003, ~220ms
```

On the demo batch, **10 of 14 lines were answered for free.**

The key property is that **abstention is a first-class outcome.** A tier that
guesses makes the cost panel meaningless — you cannot tell which answers were
earned. The ML tier returns `(None, 0.31)` rather than its best guess: it
withholds the label while still reporting how confident it was.

---

## Quickstart

```bash
git clone https://github.com/HarshCodeK/hybrid-log-classifier
cd hybrid-log-classifier

python -m venv .venv
.venv\Scripts\activate              # Windows
pip install -r requirements.txt

python train.py                     # trains the ML tier, prints both accuracy numbers
python -m pytest tests/ -q          # 46 tests, no network needed, ~2s
python -m uvicorn src.api:app --reload
```

Open **http://localhost:8000**. API docs at **/docs**.

To enable the LLM tier, copy `.env.example` to `.env` and set `GROQ_API_KEY`.
**Without a key the project still runs** — regex and ML handle everything they
can, unmatched lines come back as `Unknown` with a reason, and `/health` reports
`llm_available: false`.

---

## Try it

Paste these into the batch box:

```
[2026-09-30 02:14:01] Multiple failed login attempts detected for user admin_42
[2026-09-30 02:14:09] Failed login for user admin_42 from ip 203.0.113.7
[2026-09-30 02:14:33] Authentication failure for user admin_42 from ip 203.0.113.7
[2026-09-30 02:14:50] Access denied for user admin_42
[2026-09-30 02:16:44] Failed login for user admin_42 from ip 203.0.113.9
[2026-09-30 08:40:00] Memory usage at 94% on server node-12, threshold exceeded
[2026-09-30 08:41:12] Memory usage at 96% on server node-12
[2026-09-30 08:42:30] Out of memory error in worker on node-12
[2026-09-30 09:00:00] Health check passed for service api-gateway
[2026-09-30 09:00:05] Request served from cache in 12ms
[2026-09-30 09:05:00] Function getUserData() is deprecated, use fetchUser()
[2026-09-30 09:06:00] Data pipeline crashed during ETL step
[2026-09-30 09:07:00] Nginx returned 502 to the upstream
[2026-09-30 09:08:00] Disk is nearly full on the log volume
```

Or `curl` it:

```bash
curl -X POST localhost:8000/classify/batch \
  -H "Content-Type: application/json" \
  --data-binary @data/demo_batch.json
```

**What to look for:** the five failed logins collapse into one critical incident
sharing `user:admin_42`. The memory warnings six hours later on a different host
stay separate — same logic, different problem. Both behaviours come from one
rule: *same incident ⇔ shares an entity AND within 300 seconds.*

---

## Accuracy: the number to quote, and the one to ignore

```
Random train/test split:      1.000 accuracy   <- misleading
Template-grouped split:       0.491 accuracy   <- the real number
```

**The 1.000 is leakage, and it is mine.** The training data is 240 rows built
from 138 templates, each instantiated three times with different values. A random
split scatters siblings across both sides, so the model recognises memorised
strings rather than learning the task.

Holding out **whole templates** means every test line is a phrasing never seen in
training. Accuracy drops to 0.491.

`python train.py` prints both and labels the flattering one as leakage.
**Quote 0.491.**

| Class | Precision | Recall |
|---|---|---|
| Resource Usage | 1.000 | 1.000 |
| Security Alert | 0.364 | 1.000 |
| Unknown | 1.000 | **0.118** |
| Deprecation Warning | 1.000 | **0.200** |

High precision with low recall means the model is *conservative* — it only claims
a category when the signal is clear. For an operations tool that is the correct
failure mode: a missed deprecation notice is noise, a false security alert is a
false alarm at 2am.

**Consequence, stated plainly:** at the 0.60 threshold this tier accepts 3 of 53
lines, and on the demo batch it fired **zero** times. With 240 rows it is not yet
earning its place. See [docs/06-limitations.md](docs/06-limitations.md).

---

## Model choice, measured

Benchmarked against 15 held-out phrasings that the regex and ML tiers both
abstain on — the lines that actually reach tier 3:

| Model | Accuracy | p50 latency |
|---|---|---|
| **qwen/qwen3.8-27b** | **15/15 (100%)** | 140ms |
| openai/gpt-oss-20b | 3/10 (30%) | 434ms |
| allam-2-7b | 1/4 (25%) | 130ms |

The prompt went from **12/15 to 15/15** by adding an explicit decision rule that
counters the model's bias toward `Unknown`. You only know the first prompt was
worse because you measured it.

The model name is read from `GROQ_MODEL`, not hardcoded. The original pinned
`llama-3.3-70b-versatile`, which Groq has since retired — and it returns a hard
**404**, not a deprecation warning.

---

## API

| Endpoint | Method | What |
|---|---|---|
| `/` | GET | The web UI |
| `/classify` | POST | One line → category, confidence, explanation, cost, latency |
| `/classify/batch` | POST | Many lines → tier economics, incidents, percentiles |
| `/runs` | GET | Previous runs |
| `/runs/{id}` | GET | One run with every classification |
| `/health` | GET | Is the LLM tier usable |
| `/model/benchmark` | GET | Which model is configured and why |
| `/docs` | GET | Interactive OpenAPI docs |

Every response uses the same envelope: `category`, `confidence`, `explain`,
`cost_usd`, `latency_ms`.

---

## Layout

```
src/
├── config.py            all tunables — categories, regex rules, thresholds, severity
├── regex_classifier.py  tier 1   free, 0.02ms, explains itself
├── ml_classifier.py     tier 2   free, 1ms, trains + evaluates honestly
├── llm_classifier.py    tier 3   ~$0.00003, 220ms, measured 15/15
├── pipeline.py          routing, cost accounting, latency percentiles
├── incidents.py         entity extraction + time-window grouping  <- the product
├── store.py             SQLite run history
└── api.py               FastAPI endpoints, log parsing, static serving
static/                  hand-written HTML/CSS/JS — no framework, no build step
tests/                   46 tests, offline, ~2s
docs/                    why / architecture / stack / walkthrough / interview / limits / concepts
```

**Read these three first:** [config.py](src/config.py) (all the decisions),
[incidents.py](src/incidents.py) (the part that turns lines into incidents),
[pipeline.py](src/pipeline.py) (`classify_one` is the whole routing rule in ~30 lines).

---

## Documentation

| Document | What it answers |
|---|---|
| [Why this project](docs/01-why-this-project.md) | Why build it, and what I rejected |
| [Architecture](docs/02-architecture.md) | How it works and why each piece exists |
| [Tech stack](docs/03-tech-stack.md) | Why each library, what I chose against |
| [Walkthrough](docs/04-walkthrough.md) | Real requests, real output |
| [Interview Q&A](docs/05-interview-qa.md) | 50+ questions with defensible answers |
| [Limitations](docs/06-limitations.md) | What is broken, not merely unfinished |
| [Concepts](docs/07-concepts.md) | The fundamentals this assumes |

---

## Notable details

- **Every README example is a test.** `tests/test_readme_examples.py` asserts
  the category *and* tier for each documented line, so the docs cannot drift from
  the code. A previous version of this project had 4 of 14 documented examples
  wrong about which tier fired.
- **There is no `innerHTML` assignment anywhere in `static/`.** Log lines are
  attacker-influenced, so every value reaches the DOM through `textContent`.
- **The trained model is committed.** If it were not, every unmatched line would
  fall to the LLM on a fresh clone and the cost argument would silently
  disappear.
- **Cost is priced per model**, with a test asserting two differently-priced
  models cost differently. The number this project exists to defend cannot be the
  one that rots unnoticed.

---

## License

MIT
