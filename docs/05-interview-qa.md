---
kind: spec
title: "Interview questions and defensible answers"
comments: none
---

# Interview Q&A

Every question here is one an interviewer could actually ask after reading the
code. Answers are written to be **said out loud**, and the measured numbers are
real output from this repository.

**The rule this document exists to enforce:** every number quoted here came from
running the code. If you cannot produce it, do not claim it.

---

## The opening questions

### "What is this, in one sentence?"

> An operations tool that takes a wall of log lines and hands back a ranked list
> of incidents. The interesting part is that it tries three methods cheapest-first
> — regex, then a small model, then an LLM — and only escalates when the cheaper
> ones admit they don't know. On a 14-line batch, 10 lines were answered for free
> and the run cost about a tenth of a cent.

### "Why should anyone care about that?"

> Because the problem isn't classifying lines, it's reducing 4,000 lines to
> something a person reads in 30 seconds. The classifier is table stakes. The
> grouping is the product.

### "Walk me through what happens when I paste a log file."

> `api.py` parses timestamps out of each line. `pipeline.classify_one` tries
> regex first — if a rule matches we return immediately with the rule named. If
> not, the TF-IDF model runs and returns a category only if it's above 0.60
> confidence; otherwise it abstains. If both abstain, the LLM classifies. Then
> `incidents.py` extracts entities — host, user, IP, service — and groups lines
> that share an entity and fall within five minutes of each other. Finally
> `store.py` persists the run to SQLite and the API returns tier economics,
> latency percentiles, and the ranked incidents.

### "What's the most interesting thing in here?"

> The abstention design. A tier that always guesses makes the whole cost
> argument unverifiable, because you can't tell which answers were earned. The ML
> tier returns `(None, 0.31)` rather than its best guess. That's why the cost
> panel is meaningful.

---

## Architecture questions

### "Why three tiers instead of just calling an LLM?"

> Measured on a 14-line batch: 10 lines by regex at 0.022ms and zero dollars, 4 by
> LLM at about 220ms and $0.00003 each. That's roughly 12,000× faster on the
> majority of traffic and free. There's also explainability — when regex fires, I
> can show you the exact pattern, which is something you can put in front of an
> on-call engineer. An LLM gives you a label and nothing else.

### "What if the regex rules don't cover something?"

> That's the design. A miss falls through to ML, which handles unfamiliar
> phrasing. If the model is under 0.60 confidence, it abstains too and the line
> goes to the LLM. Every tier is allowed to say "I don't know", and the whole
> point is that a miss is recoverable rather than fatal.

### "Why is the ML model so weak?"

> Because 240 rows is not enough data. It scores 1.000 on a random train/test
> split and 0.491 when I hold out whole templates — that gap is leakage, because
> the training rows are siblings from 138 templates. The honest number is 0.491,
> and on the demo batch the tier fires zero times. It behaves correctly by
> abstaining, but it isn't earning its place yet. Real log data is the fix.

### "Why store incidents in SQLite and not something bigger?"

> Single user, one log file, no server to install. `git clone` and `pytest` work
> with nothing else. If there were a second user I'd switch, but that's a
> different product.

---

## The hard questions

### "What was the hardest bug you hit?"

> Four, and all of them looked like working code.

> The worst: I keyed incident buckets by entity set. Two incidents on the same
> user six hours apart silently overwrote each other — the first one's line count
> and timestamps were just gone. The symptom is missing data, not an error, so
> nothing looked wrong.

> Second: `row.get("note", "")` returned `None` instead of `""` because the key
> existed with a `None` value. `.startswith()` on `None` crashed the entire batch
> — on the first regex-tier line, which is most traffic.

> Third: my host regex extracted `node-12` as `12`, because it treated the hyphen
> as a separator when it's part of the name. One host's logs split across two
> incidents.

> Fourth: cost accounting. I had hardcoded Llama-3.3-70b's price as two
> constants. When I switched models, every reported cost was wrong by 6× and
> nothing failed — because the number the project exists to defend was the one
> number nobody was checking.

> None of those were findable by reading the code. They showed up when I ran
> realistic input.

### "How do you know your incident grouping is correct?"

> Four tests, each of which is a bug I actually had. Same entity and window
> merges. Same entity six hours apart does not. Different entities at the same
> moment do not. A bucket containing a high-severity line reports as high, because
> averaging severity would let a critical incident hide behind noise.

### "What's your false positive rate?"

> I don't measure it, and that's a real gap. I have per-class precision from
> `train.py` — Security Alert precision is 0.364, which means most of what it
> flags as a security event isn't one. In practice that's tolerable because the
> regex layer takes the confident cases first, but I should be logging
> ground-truth corrections to measure it properly.

### "Why is confidence `null` for the LLM tier?"

> Because the model has no calibrated probability. Any number I put there would be
> invented, and it would look like a measurement. Instead the system handles
> uncertainty structurally: low-confidence ML cases escalate, and unmatched lines
> surface as Unknown for a human to look at. The absence of a number is itself the
> information.

---

## ML and evaluation questions

### "How did you evaluate the model?"

> Two ways, and the second is the one that matters. A random split gives 1.000 —
> that's leakage, since sibling rows from the same template land on both sides.
> A `GroupShuffleSplit` holding out whole templates gives 0.491. Every test line
> is then a phrasing the model never saw.

### "Why logistic regression and not a transformer?"

> Two reasons. With 240 rows, a transformer memorises rather than generalises —
> the simplest model that can do the job is the honest choice. And
> `sentence-transformers` pulls in PyTorch, about 2GB, which would put a torch
> dependency in a project whose thesis is *don't pay for intelligence you don't
> need*. I'd be arguing against myself in my own requirements file.

### "Why 0.60 as the threshold?"

> I measured it. At 0.5, 5 of 53 held-out lines are accepted, all correct. At 0.6,
> 3 of 53, all correct. At 0.8, none. So the model's confidence is
> well-calibrated even though its accuracy is poor — it's unsure exactly where
> it's unsure. I kept 0.6 because a wrong label accepted at 0.5 is worse than an
> honest abstention.

### "What's precision vs recall look like here?"

> The model is conservative. Resource Usage is 1.000/1.000. Unknown is
> precision 1.000 but recall 0.118 — it only says Unknown when very sure, so it
> misses most of them. Security Alert is the inverse: recall 1.000, precision 0.364,
> so it catches all of them and flags extra. For an operations tool that's the
> right failure direction — a missed deprecation notice is noise, a false security
> alert is a false alarm at 2am.

### "You could have used a public log dataset. Why didn't you?"

> I tried. The problem is my five categories are operational — Security Alert,
> Resource Usage, Workflow Error, Deprecation Warning, Unknown — and public log
> datasets come with their own labels that don't map onto that taxonomy cleanly.
> Relabelling 100,000 rows by hand wasn't feasible. With more time I'd scrape a
> real service's logs and hand-label a few hundred.

---

## Engineering questions

### "How do you handle the LLM being down?"

> It degrades, it doesn't fail. `LLMUnavailable` is a named exception and the
> pipeline catches exactly that, so unrelated bugs still propagate. Unmatched
> lines come back as Unknown with a reason attached, the batch completes, and the
> cheaper tiers still classify everything they can. `/health` reports
> `llm_available` so the UI can say so before you paste anything.

### "Why no framework?"

> The pipeline is about 30 lines of `if` statements. LangChain would add a
> dependency, a learning curve, and indirection between me and the one decision
> this project is about explaining. I'd rather be able to read the routing logic
> out loud.

### "How do you test it?"

> 46 tests, about two seconds, no network. The important ones: every README
> example is asserted for category *and* tier, so the docs can't drift from the
> code. The incident-grouping tests are the four bugs above. The cost tests
> assert two differently-priced models produce different costs — which a
> hardcoded constant cannot pass.

### "Why is the model name in an environment variable?"

> Because I hardcoded it first and it broke. `llama-3.3-70b-versatile` got retired
> by the provider, and the API returns a 404 rather than a deprecation warning —
> so it surfaced as an unexplained failure. Now it reads `GROQ_MODEL` with a
> measured default.

### "How did you pick the model?"

> I benchmarked every text model available on the account against 15 held-out
> phrasings that the regex and ML tiers both abstain on. `qwen/qwen3.8-27b` got
> 15/15 at 140ms. `gpt-oss-20b` got 3/10 — it collapsed to Unknown on nearly
> everything. It's not a bad model, it's a bad instruction-follower on a
> closed-set task.

### "What was the prompt engineering?"

> The first prompt scored 12/15 and every miss was the same: the model reached
> for Unknown, because I'd told it Unknown exists and it treated that as
> permission. I added a decision rule that inverts the burden — commit to a real
> category unless the line describes nothing wrong and nothing scheduled. That
> took it to 15/15 at the same latency. I only knew the first prompt was worse
> because I measured it.

---

## Security questions

### "How do you know your frontend is safe?"

> There's no `innerHTML` assignment anywhere in `static/`. Log lines are
> attacker-influenced — a log message can contain anything a user typed — so
> every value reaches the DOM through a helper that uses `textContent`. The API
> caps batches at 5,000 lines and validates every body with Pydantic before any
> handler runs. And it binds to localhost with no auth, because it's a
> single-user local tool. If it ever listened on a network, auth is the first
> thing I'd add.

### "Why is unpickling a model file safe here?"

> It isn't inherently — unpickling executes arbitrary code. These files are
> produced by `train.py` on this machine from a CSV in the repo, and `.gitignore`
> keeps them from arriving via git. The rule is never to load a model from a URL,
> and nothing here does.

---

## Cost questions

### "How do you know the cost figures are right?"

> They're estimates at current published rates, not invoices. Tokens are estimated
> at roughly 4 characters each, plus the measured system-prompt length. Good
> enough for an order-of-magnitude comparison between tiers, which is what it's
> for. Prices are keyed by model name so they can't silently go stale — which
> happened once already.

### "What's the actual saving?"

> On the demo batch: $0.000130 spent versus $0.000459 if every line went to the
> LLM. That's 71.68% avoided. Honest caveat — that number is entirely a function
> of how formulaic the input is. Feed it logs where nothing matches a regex and
> the saving goes to zero. The architecture's value is highest on the traffic
> that's easy to write rules for, which is most real log traffic.

---

## Questions where the honest answer is "I don't know"

Say this: **"I don't know — I'd need to check. Here's how I'd find out."** Then
stop. That is a complete answer, and interviewers ask precisely to see whether
you'll bluff.

Real ones for this project:

- **"What's your false positive rate in production?"** — Not measured. No
  production data, no ground-truth logging.
- **"How does this scale to a million lines?"** — I don't know. Classification is
  O(n) and trivially parallel, but grouping is O(n·k) over candidate buckets and
  I've only tested 14 lines.
- **"How would you detect concept drift?"** — I'd log corrections when an
  operator overrides a classification and watch the category distribution shift.
  Not built.
- **"What's the latency under concurrent load?"** — Untested. Single-user local
  tool, no load testing.

---

## Questions to ask them

Good questions to turn around:

- "What's the accuracy bar for this in production — who signs off on a wrong call?"
- "When you review a flagged log, what's the signal that it was right?"
- "What's the cost ceiling before someone gets paged about the cost?"
- "If I gave you a real log file, what's the first thing you'd want to see?"

That last one is worth asking every time. It shows you care about the user's
actual workflow rather than the model's metrics.
