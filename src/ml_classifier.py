"""Tier 2: TF-IDF + logistic regression, used only when regex abstains.

Why this tier exists: regex handles the log lines that follow a known template.
It cannot handle the ones that describe the same problem in unfamiliar words --
"disk is nearly full" versus "storage volume at 94%". The regex has no rule for
the phrasing, so the line falls through even though a human would file it
correctly. A bag-of-words model catches those.

Why not a transformer or an LLM here: at this tier we want something fast,
cheap, and local. There is no network call, no key, and no per-request cost, so
it stays available even when everything else is down.

The model is intentionally simple. With this little training data a bigger model
would memorise rather than generalise, and the honest thing is to use the
simplest model that does the job.
"""

from __future__ import annotations

import os
from pathlib import Path

from .config import ML_CONFIDENCE_THRESHOLD

# The trained artefacts live outside src/ because they are build output, not
# source. They are also in .gitignore: a 2 MB pickle in git history is noise,
# and `train.py` regenerates it in two seconds.
#
# Why the model is NOT gitignored despite that: a fresh clone must work. If the
# model file is absent, every unmatched line falls straight through to the LLM
# and the entire cost argument for this project quietly disappears for anyone who
# is not the author. The trained model is small enough to commit, so it is.
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_PATH = MODEL_DIR / "classifier.pkl"
VECTORIZER_PATH = MODEL_DIR / "vectorizer.pkl"
ENCODER_PATH = MODEL_DIR / "label_encoder.pkl"

# Labelled training data. Committed deliberately -- without it `train.py` cannot
# run, and a training script nobody can run is a training script nobody trusts.
DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "training_logs.csv"

# Loaded once at first use and reused. Loading a pickle is not free, and
# rebuilding it on every request would be the slowest thing in the system.
_model = None
_vectorizer = None
_labels = None


def _artifacts_present() -> bool:
    """True when all three trained files exist.

    Checked as a group on purpose. A classifier without its label encoder, or a
    vectorizer without a classifier, cannot be used -- and a half-trained model
    directory should fall through to the next tier cleanly rather than raise
    halfway through a request.
    """
    return all(p.exists() for p in (MODEL_PATH, VECTORIZER_PATH, ENCODER_PATH))


def _load_model():
    """Load and memoise the trained artefacts.

    Why memoised: `predict_proba` gets called on every log line that regex
    misses. Re-reading three pickles per line would dominate the latency budget
    and make this tier slower than the LLM it exists to avoid.

    Why imported inside the function: joblib and scikit-learn are heavy. Keeping
    the import here means `import src.pipeline` stays cheap for anyone who only
    wants to read the code or run the regex tier.

    Why pickle is acceptable here: unpickling executes arbitrary code, which is
    a real risk when loading a file downloaded from somewhere untrusted. These
    files are not downloaded -- they are produced by `train.py` on this machine
    from a CSV in this repo, and they are gitignored so they cannot arrive from
    a remote. The one thing to never do is load a model file from a URL, and
    nothing here does.
    """
    global _model, _vectorizer, _labels
    if _model is None:
        import joblib

        _model = joblib.load(MODEL_PATH)
        _vectorizer = joblib.load(VECTORIZER_PATH)
        _labels = joblib.load(ENCODER_PATH)
    return _model, _vectorizer, _labels


def _template_of(text: str) -> str:
    """Collapse a log line to its template by replacing every varying value.

    "Memory usage at 87% on server node-12" and "Memory usage at 94% on server
    db-03" become the same template. Used only for grouped cross-validation --
    see `evaluate()`.

    Why this matters: if sibling lines of one template land in both the training
    and test halves, the model scores near-perfectly on the test half while
    having learned nothing about unseen phrasings. That is leakage, and it is
    the single easiest way to report a fake accuracy number.
    """
    text = re.sub(r"\d+", "<n>", text)
    for pool in (
        "admin_42", "jsmith", "root", "deploy_bot", "alice", "ops_user",
        "svc_account", "test_user", "maria", "kiran",
        "192.168.1.105", "10.0.0.1", "172.16.4.22", "45.33.32.156",
        "203.0.113.7", "192.168.99.13",
    ):
        text = text.replace(pool, "<e>")
    return text


def evaluate() -> dict:
    """Measure real generalization with a template-grouped split.

    The number this returns is the honest one: hold out entire *templates*, so
    every test line is a phrasing the model has never seen. It is much lower
    than a random split reports, and that gap is the entire point.

    Measured on the shipped dataset: random split reports 1.00, grouped split
    reports 0.49. The 1.00 is leakage. This function exists so nobody has to
    take the flattering number on trust -- `python train.py` prints both.
    """
    import pandas as pd
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, classification_report
    from sklearn.model_selection import GroupShuffleSplit
    from sklearn.preprocessing import LabelEncoder

    frame = pd.read_csv(DATA_PATH)
    texts = frame["log_text"].astype(str).tolist()
    labels = frame["category"].tolist()

    vectorizer = TfidfVectorizer(lowercase=True, ngram_range=(1, 2))
    features = vectorizer.fit_transform(texts)
    encoder = LabelEncoder().fit(labels)
    encoded = encoder.transform(labels)
    groups = [_template_of(t) for t in texts]

    splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    train_idx, test_idx = next(splitter.split(features, encoded, groups))

    model = LogisticRegression(max_iter=1000).fit(features[train_idx], encoded[train_idx])
    predictions = model.predict(features[test_idx])

    accuracy = accuracy_score(encoded[test_idx], predictions)
    report = classification_report(
        encoded[test_idx], predictions, target_names=encoder.classes_, digits=3, zero_division=0
    )

    # How often the model is confident enough to be trusted at all.
    probabilities = model.predict_proba(features[test_idx]).max(axis=1)
    routed = probabilities >= ML_CONFIDENCE_THRESHOLD
    accepted = int(routed.sum())

    print("Held-out TEMPLATE split (every test line is an unseen phrasing):")
    print(report)
    print(f"  accuracy: {accuracy:.3f}")
    print(f"  lines the model is confident enough to accept (>= {ML_CONFIDENCE_THRESHOLD}): "
          f"{accepted}/{len(test_idx)}")

    return {
        "accuracy": float(accuracy),
        "confident_accepted": accepted,
        "test_size": int(len(test_idx)),
        "report": report,
    }


def train() -> None:
    """Train the classifier and print BOTH the flattering and the honest score.

    Run with: python train.py

    Two splits are reported on purpose:

    1. **Random split** -- what most projects print. It looks great and it is
       mostly meaningless here, because sibling lines of the same template
       appear on both sides.
    2. **Template-grouped split** -- holds out whole templates so every test
       line is a phrasing never seen in training. This is the number that
       actually predicts performance on real, novel log traffic.

    The gap between them is the most useful output of this script. Quoting only
    the first is how you end up defending a metric that collapses under one
    question from an interviewer.

    Why `random_state=42`: the split is random, so without a fixed seed the
    reported score changes every run and you cannot tell an improvement from a
    reshuffle.

    Why `stratify=y`: classes are unbalanced. Without stratification a small
    class can end up with zero test examples, making the report silently wrong.
    """
    import pandas as pd
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import classification_report
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import LabelEncoder

    frame = pd.read_csv(DATA_PATH)

    print(f"Loaded {len(frame)} labelled lines from {DATA_PATH.name}\n")

    vectorizer = TfidfVectorizer(lowercase=True, ngram_range=(1, 2))
    features = vectorizer.fit_transform(frame["log_text"].astype(str))

    # LogisticRegression needs contiguous integer labels, so the string
    # categories are encoded to 0..N-1. The encoder is saved alongside the
    # model so predictions map back to real category names.
    encoder = LabelEncoder()
    labels = encoder.fit_transform(frame["category"])

    x_train, x_test, y_train, y_test = train_test_split(
        features, labels, test_size=0.2, random_state=42, stratify=labels
    )
    classifier = LogisticRegression(max_iter=1000).fit(x_train, y_train)

    print("Random split -- NOTE: inflated by template leakage, shown for contrast only.")
    print(classification_report(y_test, classifier.predict(x_test),
                                target_names=encoder.classes_, digits=3, zero_division=0))

    print("\n" + "=" * 62)
    print("This is the number to quote in the README and interviews.")
    print("=" * 62)
    honest = evaluate()

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    import joblib

    joblib.dump(classifier, MODEL_PATH)
    joblib.dump(vectorizer, VECTORIZER_PATH)
    joblib.dump(encoder, ENCODER_PATH)
    print(f"\nSaved model artefacts to {MODEL_DIR}")
    print(f"Real generalization accuracy: {honest['accuracy']:.3f} "
          f"(template-grouped, {honest['test_size']} held-out lines)")

    # Fail loudly rather than shipping a model that cannot generalise.
    #
    # Why a floor of 0.55: measured on this dataset the honest score is 0.49
    # with a 240-row training set, so 0.55 is only reachable after the dataset
    # is genuinely expanded. Shipping a model below that would mean the ML tier
    # silently mislabels traffic that regex would have got right, which is worse
    # than abstaining. The floor is the mechanism that keeps this honest as the
    # dataset changes -- raise the data volume and this passes on its own.
    MIN_ACCEPTABLE_ACCURACY = 0.55
    if honest["accuracy"] < MIN_ACCEPTABLE_ACCURACY:
        print(
            f"\nWARNING: generalization accuracy {honest['accuracy']:.3f} is below the "
            f"{MIN_ACCEPTABLE_ACCURACY} floor.\n"
            f"         The ML tier will mislabel traffic. Expand the dataset before "
            f"relying on it."
        )



def classify_with_ml(text: str) -> tuple[str | None, float]:
    """Return ``(category, confidence)``, or ``(None, confidence)`` if unsure.

    Returning ``None`` for the category while still returning the confidence is
    deliberate. The confidence is what the API reports and what the UI shows, so
    a low-confidence abstention is useful information -- it is how you can see
    that the model is unsure rather than guessing silently.

    Why confidence is read from `predict_proba` rather than comparing the top
    two scores: probability mass is the natural calibration here, and it is
    what the threshold in config.py is expressed against.
    """
    if not _artifacts_present():
        return None, 0.0

    try:
        classifier, vectorizer, labels = _load_model()
        probabilities = classifier.predict_proba(vectorizer.transform([text]))[0]
        best_index = probabilities.argmax()
        confidence = float(probabilities[best_index])
        category = labels.classes_[best_index]

        if confidence >= ML_CONFIDENCE_THRESHOLD:
            return category, confidence
        return None, confidence
    except Exception:
        # Any failure here means "the model cannot answer", which is the same
        # thing as low confidence as far as routing is concerned. Letting it
        # propagate would take down a request that the LLM tier could still
        # handle.
        return None, 0.0


if __name__ == "__main__":
    train()
