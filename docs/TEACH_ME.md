# TEACH_ME — Hybrid Log Classifier

Read this once slowly. Then ask me anything. Then I quiz you.

## 1. What the project does, in one sentence

Every application log line gets a category (Security Alert, Resource Usage,
Deprecation Warning, Workflow Error, Unknown), and lines are collapsed into a
short, ranked list of incidents — so a human reads "6 incidents, 1 critical"
instead of 4,000 raw lines at 2am.

## 2. The one idea: the router

Not every line deserves an LLM. So each line goes down a waterfall:

```
log line
   |
   v
regex tier -- matched? -------------------------> done. free, ~0.02 ms, certain
   | no
   v
ML tier -- confident >= 0.60? ------------------> done. free, ~1 ms
   | unsure
   v
LLM tier ---------------------------------------> done. ~200 ms, costs money
```

If none fire: the line is `Unknown` and costs nothing extra.

The cost claim on your resume rests entirely on this waterfall: the expensive
tier only sees lines the two free tiers already declined.

## 3. Resume bullet → where it lives

| Your resume says | Really lives in |
|---|---|
| three-tier pipeline Regex → ML → LLM | `src/pipeline.py` — `classify_one()` tries regex, then ML, then LLM |
| confidence-based routing | `src/ml_tier.py` — confidence from `predict_proba`, threshold in `src/config.py` (0.60) |
| FastAPI REST API | `src/api.py` — `/classify`, `/classify/batch`, `/health`, `/models`, `/runs` |
| Streamlit interface | `app.py` — `streamlit run app.py` |
| results persisted to SQLite | `src/store.py` — one table `runs`, raw `sqlite3` |
| scikit-learn | `src/ml_tier.py` — `TfidfVectorizer` + `LogisticRegression` |
| Groq | `src/llm_tier.py` — `Groq` client, model ids in `src/models.py` |

## 4. File by file, what it does and why

- **`src/regex_tier.py`** — a list of `(category, regex)` pairs. First match
  wins, specific patterns before general ones. Also `extract_entities()` pulls
  out user/ip/host/service from each line — needed for grouping. Patterns are
  deliberately strict: a lesson in the comments says bare words like "admin"
  must not become usernames.
- **`src/ml_tier.py`** — loads `models/classifier.pkl` once. `classify()`
  returns `(category, confidence)` when confident, `(None, confidence)` when
  not. That `(None, ...)` is the important part: **abstention**. Also `train()`
  which fits the model and prints TWO accuracy numbers (see §6).
- **`src/llm_tier.py`** — only reached when regex and ML both decline and a
  `GROQ_API_KEY` exists. Sends the line + a strict prompt to Groq, returns the
  category string and a cost from the provider's token counts.
- **`src/pipeline.py`** — the waterfall plus the batch summary: tier counts,
  total cost, "naive" cost (what if every line hit the LLM), cost-avoided %,
  latency p50/p95, and the incident list.
- **`src/incidents.py`** — the grouping rule: same incident ⇔ share at least
  one entity AND within 300 seconds (`INCIDENT_WINDOW_SECONDS`). Sorted
  worst-first by severity rank then size. Why both halves: entity-only merges
  a week of `db-01` timeouts into one blob; time-only merges unrelated errors.
- **`src/api.py`** — thin FastAPI routes over the pipeline. Pydantic validates
  text length and batch size.
- **`src/store.py`** — append one row per batch into a `runs` table. Raw
  `sqlite3`, deliberately — one table does not justify an ORM.
- **`src/config.py`** — the tunables: ML threshold 0.60, incident window 300s,
  DB path.
- **`src/models.py`** — every model id + price in one file, because a retired
  hardcoded model id once 404'd this project in production.
- **`app.py`** — Streamlit UI: paste logs, see stats, incidents, download JSON.
- **`train.py`** — CLI wrapper around `ml_tier.train()`.
- **`tests/test_classifier.py`** — 27 tests, no network required.
- **`java/`** — a Java CLI mirroring the regex tier + grouping, emitting the
  same JSON. A Java test asserts the shape matches, so a shape change in either
  language fails loudly. This is why Java appears on your resume.

## 5. The run you should be ready to do live

```bash
pip install -r requirements.txt
python train.py                      # prints the two accuracy numbers
streamlit run app.py                 # UI
uvicorn src.api:app --reload         # API on :8000/docs
python -m pytest tests/ -q           # 27 tests
```

## 6. The accuracy question — the one interviewers will ask

`train.py` prints:

```
random split accuracy : 1.000   <- LEAKY, siblings on both sides
template-grouped      : 0.833   <- the real number
```

Why: training data is 31 line templates, each written 3 times. A random split
py puts near-identical rows on both sides, so the model memorises — score
1.000, meaningless. Grouping by `template_id` forces it to generalise to
unseen phrasings — 0.833, the honest number. **If asked one number, say
0.833.** Volunteering the leakage story is a strength, never a weakness.

## 7. Things to say when you don't know

"I don't know — but here's exactly where I'd check" — then the file name.
That is a complete, safe answer. Bluffing is the only unrecoverable move.

## 8. What NOT to claim

- Do not say the ML tier is "accurate". Say "the regex tier answers most of
  it for free, and the ML tier answers the rest only when confident".
- Do not name a model id from memory unless you open `src/models.py`.
- Do not say Docker runs locally. Dockerfiles exist and CI builds them.
- Cost numbers are estimates from provider token counts, not invoices.

## 9. Quick self-check before I quiz you

Without looking: (a) what does the ML tier return when unsure, (b) what two
conditions define an incident, (c) why is the random-split accuracy
meaningless, (d) which file holds all model prices, (e) what stops an LLM call
when no key is set, (f) what does `java/` actually verify.
