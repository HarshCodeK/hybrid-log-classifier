# Interview Q&A — Hybrid Log Classifier

Answers should be said in your own words. Each one names the concept, the
component in this repo, and the tradeoff. If you cannot say one of those three,
reread the component.

## The 30-second pitch

"It assigns every log line to a category, then collapses lines into a handful of
ranked incidents. The interesting part is routing: regex first because it is
free and certain, then a small TF-IDF model, then a paid LLM only for what the
other two decline. The goal is to spend LLM money only on lines that genuinely
need it."

## Q: Why three tiers instead of one model?

A: Cost, latency, and certainty trade differently per line. Roughly 70-90% of
lines in these logs contain a keyword ("failed login") that makes the answer
deterministic — paying a model for those is waste. The middle tier covers
common phrasings for free. The LLM is the expensive, slow, probabilistic tier,
so it should see the least traffic. In the demo, 10 of 11 lines never left the
regex tier and cost avoided was 100%.

## Q: What is abstention and why does it matter?

A: When the ML tier's confidence is below 0.60 it returns `(None, confidence)`
instead of its best guess. If every tier always answered, some answers would be
guesses, and you could never tell which ones were earned — the cost-saving
claim would be unverifiable. The abstain path ends in `tier="none"` ->
`"Unknown"`, which the user can handle. Design principle: "I don't know" is a
first-class outcome, not an error.

## Q: Why logistic regression and TF-IDF?

A: The task is five-way short-text classification over a few hundred rows.
Logistic regression trains in under a second, has three dependencies, and
exposes `predict_proba` — the confidence gate needs probabilities, so we can
threshold them. A neural net would add GPU/training/tuning surface for no
measurable gain at this data size. Against: regex is rule-based and brittle;
a transformer would capture context but is disproportionate here. TF-IDF +
logistic regression is the honest minimum that works.

## Q: Your ML accuracy is 0.833 — walk me through why not 1.0.

A: The dataset is 31 templates, each written three times with different values.
A random train/test split puts near-identical rows in both sets, so the model
memorises strings and scores 1.000 — that is data leakage. Grouping by
`template_id` (GroupKFold) forces the model to generalise to phrasings it has
never seen; the real number is 0.833. `train.py` prints both and labels the
flattering one as leaky. If an interviewer asks only one number, say 0.833.

## Q: Why TF-IDF when you claim "embeddings" elsewhere on your resume?

A: Different problems. In the financial assistant, questions and policy text
share almost no vocabulary, so semantic embeddings earn their dependency. In the
log classifier, categories are delimited by strong keywords and training data is
small — TF-IDF is sufficient, simpler, and deterministic. Choosing the
cheapest tool that meets the requirement is the engineering decision, not a
compromise.

## Q: How does incident grouping work?

A: Two lines are the same incident iff they share at least one extracted entity
(user, ip, host, service) AND fall within 300 seconds of each other. Both halves
are necessary: sharing an entity with no time bound merges every timeout for a
host across a week; a time bound with no shared entity merges unrelated errors
that merely occurred together. Worst-first sort is by severity rank then line
count.

## Q: Entity extraction looks fragile. IS it?

A: Yes, and it is stated in the README's limits. It covers four entity kinds
with regexes; real logs carry request IDs, trace IDs, pod names. The current
implementation is honest about that rather than pretending completeness.

## Q: How do you avoid double-counting or mis-pricing LLM cost?

A: All model ids and prices live in one file (`src/models.py`); nothing
hardcodes a price. Cost is computed from the provider's reported token counts,
so every call is priced against the exact model that served it. "Naive cost"
assumes every line went to the LLM at 120-in/15-out tokens; the ratio of actual
to naive is the cost-avoided number.

## Q: What happens when the LLM tier is unavailable?

A: The pipeline degrades gracefully: `allow_llm=False` or a missing
`GROQ_API_KEY` means unmatched lines return `tier="none"`, category
`"Unknown"`. The API still works, the UI still renders, telemetry still flows.
Same pattern as the other projects: the system never dies because a paid or
networked tier is off.

## Q: How is the FastAPI service structured?

A: Thin routes over `src/pipeline.py`. `POST /classify` for one line,
`POST /classify/batch` for a batch (the only place where incidents and cost
economics exist), `GET /health` for tiers + LLM availability, `GET /models` for
the registry, `GET /runs` for SQLite history. Validation is pydantic
(`min_length`, `max_length` on text and batch size).

## Q: Why SQLite via raw sqlite3 instead of an ORM?

A: One table, six columns, a single process. `sqlite3` is stdlib — an ORM
would be a dependency with no work to do. `store.save` writes the whole summary
JSON as the `summary` column, so the history row is a faithful snapshot, not a
lossy projection.

## Q: What is the Java piece doing here?

A: `java/` contains `LogTriage`, a standalone Java CLI that mirrors the Python
regex tier and the incident-grouping rule, emitting the same JSON shape. The
point is a boundary check: the JSON contract between the classifier and its
consumers is asserted by a Java test, so a change to the shape in either
language fails somewhere explicit instead of in production. It also gives a
real answer if asked why Java is on the resume.

## Q: What is deliberately NOT in this project?

A: No async, no queue, no concurrency, no auth, no rate limiting — a
single-process local tool does not need them. No vector store: retrieval is not
the problem being solved. No Java in the request path: it is a contract check,
not a hot path. Adding any of these would require a reason, not a resume line.

## Q: What would you change first in production?

A: Ordered roughly by risk: (1) real log dataset for the ML tier — 0.833 on
31 templates is a starting point, not a SLA; (2) entity extraction coverage;
(3) TOCTOU/symlink concerns are limited here since there is no file-access
boundary like megaproject, but secrets and rate limits would matter if exposed;
(4) cost figures are provider estimates, not billing reconciliation.

## Q: How do you test this?

A: 27 offline tests. Tier routing, abstention, cost accounting, incident
grouping (entity+window rule), timestamps, API contract, and the Java shape
contract. No test hits the network; LLM behaviour is tested through fakes. The
docs are not excluded: README numbers and the demo batch are re-derived from the
code, so a stale README fails the suite — documentation that lies is a bug.
