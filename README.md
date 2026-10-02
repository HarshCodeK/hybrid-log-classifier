# Hybrid Log Classifier

Classifies application log lines into operational categories using three tiers,
and collapses them into ranked incidents.

```
log line
   |
   v
regex   -- matched? ------------------> done.  free, ~0.02 ms
   | no
   v
ML      -- confident enough? ---------> done.  free, ~1 ms
   | unsure
   v
LLM     -----------------------------> done.  ~200 ms, costs money
```

**Python · FastAPI · scikit-learn · Groq · SQLite · Streamlit**

---

## The one idea

**Abstention is a first-class outcome.**

The ML tier returns `(None, confidence)` when it is unsure, instead of its best
guess. If every tier always answers, you cannot tell which answers were earned
and the cost-saving argument becomes unverifiable. A tier that says "I don't
know" is what makes routing worth anything.

---

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env          # add your GROQ_API_KEY (optional)
python train.py               # trains the ML tier, prints both accuracies
streamlit run app.py          # UI at http://localhost:8501
```

Or the API:

```bash
uvicorn src.api:app --reload  # docs at http://localhost:8000/docs
curl -X POST localhost:8000/classify/batch \
  -H "Content-Type: application/json" \
  -d '{"lines":[{"text":"Failed login for user admin_42 from ip 203.0.113.7"}]}'
```

Without `GROQ_API_KEY` everything still works — the LLM tier is simply off and
unmatched lines come back as `Unknown`.

---

## Accuracy: quote 0.833, not 1.000

```
random split accuracy : 1.000   <- LEAKY
template-grouped      : 0.833   <- the real number
```

The training data is 31 templates each written three times. A random split puts
near-identical rows on both sides, so the model scores near-perfectly by
recognising strings it has already seen. Holding out whole templates measures
how it behaves on phrasings it has not met.

`train.py` prints both and labels the flattering one as leakage. **Quote 0.833.**

Anyone can check this in ten lines, which is why it is worth saying out loud.

---

## How incidents are grouped

Two lines are the same incident when they share at least one entity **and** fall
within 300 seconds of each other.

Both halves are necessary. Sharing an entity with no time bound merges every
timeout for `db-01` across a whole week into one endless incident. A time bound
with no shared entity merges unrelated errors that merely happened together.

Measured on `data/demo_batch.json` (11 lines):

```
[critical] Security Alert       5 lines  user:admin_42, ip:203.0.113.7, ip:203.0.113.9
[high    ] Workflow Error       1 line
[high    ] Workflow Error       1 line
[medium  ] Resource Usage       2 lines  host:node-12
[low     ] Deprecation Warning  1 line
[low     ] Unknown              1 line
```

6 incidents, not 5: the two Workflow Error lines mention no shared entity, so
the grouping rule keeps them apart. 10 of 11 lines answered by regex. Cost
avoided: 100%.

---

## Layout

| File | What it does |
|---|---|
| `src/regex_tier.py` | Patterns and entity extraction |
| `src/ml_tier.py` | TF-IDF + logistic regression, with abstention |
| `src/llm_tier.py` | The paid tier |
| `src/pipeline.py` | Routing, batch summary, cost accounting |
| `src/incidents.py` | Grouping lines into incidents |
| `src/api.py` | FastAPI service |
| `src/store.py` | SQLite run history |
| `src/models.py` | Model ids and prices, in one file |
| `train.py` | Trains the ML tier, reports both accuracies |

---

## Why these choices

**Logistic regression over a neural net.** Five-way text classification over 93
rows. It trains in under a second, needs three dependencies, and exposes
`predict_proba`, which the confidence gate requires.

**SQLite over Postgres.** One user, one machine, one table. No server to install.

**Hand-rolled routing over LangChain.** The whole router is a few `if` branches.
A framework would obscure the one decision worth explaining.

**Cost keyed to model id.** Prices live in `src/models.py` and are looked up by
id. An earlier version used a `default` fallback row that silently mis-priced
any model not in the table.

---

## Interview Q&A

`docs/INTERVIEW_QA.md` — the pitch, every tradeoff, and the questions an
interviewer will actually ask, with answers grounded in this code.

## Known limits

- **The ML tier is weak on unseen phrasings** (0.833, and the categories are
  unevenly represented). The binding constraint is the 31-template dataset, not
  the model. Real log data would fix it; a different classifier would not.
- **Entity extraction covers four kinds** — user, IP, host, service. Real logs
  carry request IDs, trace IDs, pod names and HTTP status codes.
- **Batch processing is serial.** Fine at demo scale.
- **Cost figures are estimates**, from token counts returned by the provider.
  Accurate enough to compare tiers; not billing reconciliation.
