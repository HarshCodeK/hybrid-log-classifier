---
kind: spec
title: "Tech stack — why each library is here"
comments: none
---

# Tech stack

Every choice below is a decision I can defend, including the ones where a
different library was the better answer. Where I compared options, I say what I
chose against and why.

## The dependency list

```text
fastapi      uvicorn    pydantic     scikit-learn   pandas
joblib       groq       python-dotenv pytest
```

Ten direct dependencies. `pip install -r requirements.txt` pulls 134 packages
transitively; 15 of those are ones this code imports directly.

## Why each one

### `fastapi` + `uvicorn` — the API

**Chosen over:** Flask, Django, raw `http.server`.

FastAPI gives three things I would otherwise write by hand: Pydantic validation
on every request body, a generated OpenAPI page at `/docs` where an interviewer
can click through the API without reading code, and automatic `/docs` that stays
in sync because it is derived from the same models that validate.

Flask would be marginally less code for this surface. But the validation is the
part I would write badly myself — a 5,000-line batch of arbitrary strings is
exactly the input where you want a schema, and FastAPI gets it for free.

**What I would replace it with:** nothing. This is the right tool.

### `pydantic` — request validation

Arrives with FastAPI. Explicitly listed because it appears in the request models,
not just as FastAPI's internals.

`BatchRequest` caps at 5,000 lines and `ClassifyRequest` at 2,000 characters.
Those caps are a security control as much as a UX one: they bound the work a
single request can cause. They are enforced here, before any handler runs.

### `scikit-learn` — the ML tier

**Chosen over:** a neural network, a fine-tuned transformer, plain Naive Bayes.

The task is a five-way text classification over ~240 rows. Logistic regression
with TF-IDF is the standard strong baseline for that, trains in under a second,
produces `predict_proba` (which the confidence threshold needs), and has three
dependencies I can reason about.

**Why not a transformer:** embeddings from a pretrained model would likely beat
TF-IDF on accuracy. But `sentence-transformers` pulls in PyTorch — roughly 2GB of
installed package — and then I have a torch dependency in a project whose entire
thesis is *not paying for intelligence you don't need*. That would be arguing
against myself in the dependency list.

**What I would change:** more training data first, a better model second. Neither
helves if the model is trained on 240 hand-written rows.

### `pandas` — loading the training CSV

**Chosen over:** the stdlib `csv` module.

`csv` would work. Pandas gives a DataFrame that scikit-learn's train/test split
consumes directly, plus `stratify=` support that the stdlib has no equivalent of.
Class imbalance is exactly the thing that makes a naive split silently misleading,
so stratification is worth one dependency.

**What I would replace it with:** nothing. If this grew to a database-backed
training pipeline, `csv` would be fine at that point too.

### `joblib` — model persistence

**Chosen over:** pickle, ONNX, a custom format.

scikit-learn's own `dump`/`load` are joblib under the hood, so this is the
blessed path for models containing numpy arrays. Storing three artefacts
(classifier, vectorizer, label encoder) is required because they must be
version-consistent — a vectorizer trained against different features produces
silently wrong predictions, not an error.

**On the security question:** unpickling executes arbitrary code. These files are
produced by `train.py` on this machine from a CSV in this repository, and
`.gitignore` blocks them from arriving via git. The one thing never to do here is
load a model from a URL. Nothing in this codebase does.

### `groq` — the LLM provider

**Chosen over:** OpenAI, Anthropic, Ollama (local).

Groq's inference is fast enough that the LLM tier is ~200ms rather than ~2s,
and it has a free tier, which is what makes the "run my portfolio project"
argument work. Every call is isolated in `llm_classifier.py` behind one function,
so switching providers means rewriting one file.

**The honest caveat:** the specific model changed underneath me. The original
pinned `llama-3.3-70b-versatile`, which Groq has since retired — and it returns
a hard **404**, not a deprecation warning. That surfaced as an unexplained
failure, not an obvious one. The model name is now read from `GROQ_MODEL` with a
measured default, precisely because hardcoding a model name is how you get
debugged by a 404 six months later.

### `python-dotenv` — configuration

Loads `.env` so the API key is not in the shell history or committed. Optional:
every call site is wrapped in `try/except ImportError`, so the project runs
without it and the failure mode is "no key", not "ImportError".

### `pytest` — tests

**Chosen over:** unittest.

`parametrize` is what makes the regression tests compact. The incident-grouping
tests cover nine cases in about forty lines, and the README-example tests cover
every documented example from one table. In unittest that is nine `test_`
methods with repetitive bodies.

46 tests, ~2 seconds, **no network access required** — every test runs with the
LLM tier disabled.

## The model choice, measured not assumed

I benchmarked every text model available on the Groq account against a 15-line
held-out set of phrasings that the regex and ML tiers both abstain on — the lines
that actually reach tier 3 in production:

| Model | Accuracy | p50 latency | Verdict |
|---|---|---|---|
| **qwen/qwen3.8-27b** | **15/15 (100%)** | 140ms | chosen |
| openai/gpt-oss-20b | 3/10 (30%) | 434ms | collapsed to Unknown |
| allam-2-7b | 1/4 (25%) | 130ms | fast but wrong |

`gpt-oss-20b` is not a bad model. It is a poor instruction-follower on a
closed-set task, which is all this tier asks of it.

`GET /model/benchmark` reports the configured model without spending money on a
live probe. `batch.py` in `tests/` re-runs the benchmark on demand.

## The prompt is versioned, because it was measured

The first prompt scored **12/15**. Every miss was the same failure: the model
reached for `Unknown`, because I had told it `Unknown` exists and it treated that
as permission.

The fix was an explicit decision rule that inverts the burden:

```
Decision rule: decide BEFORE you read the Unknown description. A line that
reports a failure, a threshold, or a scheduled change belongs in one of the
four real categories. Choose Unknown only for lines that describe nothing
wrong and nothing scheduled.
```

**12/15 → 15/15 at the same latency.** You only know the first prompt was worse
because you measured it, which is the whole argument for keeping prompt versions
in the repo rather than in a memory.

## Cost accounting

Prices are keyed by model name in `pipeline.MODEL_PRICES`, not hardcoded as
constants. That is not tidiness — it is a bug I introduced and fixed. The table
originally held Llama-3.3-70b's rates as two bare constants; when the model
changed, the reported costs silently carried the wrong price and **nothing
failed**. The number this project exists to defend cannot be the one number that
rots unnoticed, so `tests/test_cost.py` now asserts two differently-priced
models produce different costs.

Token counts are estimated at ~4 characters per token plus the measured system-prompt
length (299 tokens). Accurate enough for an order-of-magnitude comparison between tiers, which
is what the number is for. Not accurate enough for billing reconciliation, and
not presented as such.

## What is deliberately absent

| Not used | Why |
|---|---|
| LangChain, LangGraph | The pipeline is 30 lines of `if`. A framework would obscure the one decision this project is about. |
| Streamlit | Its model is "script reruns on every interaction", which fits data exploration, not a batch job that returns a report. Also removes the weakest line from my resume. |
| React / Vue / any build step | Eight components, one fetch, no shared state. `git clone` + `uvicorn` is the whole setup. |
| Docker | On my resume but not yet in this repo. It is a genuine gap, not a considered rejection — see [limitations](06-limitations.md). |
| PostgreSQL | Single-user local tool. SQLite ships with Python; there is no server to install. |
| ChromaDB | Not needed here. There is no embedding step — this project retrieves nothing. It belongs in the financial assistant project. |

## Reproducing the environment

```bash
python -m venv .venv
.venv\Scripts\activate              # Windows
pip install -r requirements.txt
python train.py                     # trains + prints both accuracy numbers
python -m pytest tests/ -q          # 46 tests, offline, ~2s
python -m uvicorn src.api:app --reload
```

Set `GROQ_API_KEY` in `.env` to enable tier 3. Without it the project still runs
— the health endpoint reports `llm_available: false` and unmatched lines come
back as Unknown.

```bash
# Reproduce the demo numbers in the README
python -m uvicorn src.api:app &
curl -X POST localhost:8000/classify/batch \
  -H "Content-Type: application/json" \
  --data-binary @data/demo_batch.json
```
