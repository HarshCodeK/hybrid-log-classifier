"""Tier 2: TF-IDF + logistic regression. Free, ~1ms, sometimes unsure.

The important design decision here is abstention. When confidence is below the
threshold this tier returns (None, confidence) instead of its best guess.

Why that matters: if every tier always answers, you cannot tell which answers
were earned, and the whole cost-saving argument becomes unverifiable. A tier
that says "I don't know" is what makes the routing worth anything.
"""
import os

from .config import ML_CONFIDENCE_THRESHOLD

_VECTORIZER = None
_CLASSIFIER = None
_LABELS = None


def _load():
    """Load the trained model once, on first use."""
    global _VECTORIZER, _CLASSIFIER, _LABELS
    if _CLASSIFIER is not None:
        return True
    try:
        import joblib
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _CLASSIFIER = joblib.load(os.path.join(here, "models", "classifier.pkl"))
        _VECTORIZER = joblib.load(os.path.join(here, "models", "vectorizer.pkl"))
        _LABELS = joblib.load(os.path.join(here, "models", "labels.pkl"))
        return True
    except Exception:
        # No trained model: this tier simply does not exist for this process.
        return False


def classify(line: str):
    """Return (category, confidence), or (None, confidence) when unsure."""
    if not _load():
        return None, 0.0
    try:
        probs = _CLASSIFIER.predict_proba(_VECTORIZER.transform([line]))[0]
        best = int(probs.argmax())
        confidence = float(probs[best])
        if confidence >= ML_CONFIDENCE_THRESHOLD:
            return str(_LABELS[best]), confidence
        return None, confidence
    except Exception:
        return None, 0.0


def train(csv_path: str, min_accuracy: float = 0.55):
    """Train on the CSV and print two accuracy numbers.

    Two numbers, because the flattering one is misleading here. The training
    data contains repeated phrasings, so a random split can put near-identical
    rows on both sides. Holding out whole templates is the honest measure of how
    it behaves on unseen phrasings.
    """
    import joblib
    import pandas as pd
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, classification_report
    from sklearn.model_selection import GroupKFold, train_test_split
    from sklearn.preprocessing import LabelEncoder

    df = pd.read_csv(csv_path)
    X_text = df["log_text"].astype(str)
    y_raw = df["category"]

    le = LabelEncoder()
    y = le.fit_transform(y_raw)

    # --- the number a random split gives (leaky, printed for contrast) ---
    vec_a = TfidfVectorizer(ngram_range=(1, 2))
    Xa = vec_a.fit_transform(X_text)
    Xtr, Xte, ytr, yte = train_test_split(Xa, y, test_size=0.2, random_state=42, stratify=y)
    clf_a = LogisticRegression(max_iter=1000).fit(Xtr, ytr)
    leaky = accuracy_score(yte, clf_a.predict(Xte))

    # --- the number that means something (grouped by template) ---
    groups = df["template_id"] if "template_id" in df.columns else pd.Series(range(len(df)))
    gkf = GroupKFold(n_splits=5)
    scores = []
    for tr, te in gkf.split(X_text, y, groups):
        # Fit TF-IDF only on the training fold. Fitting IDF on all rows would
        # leak test-fold statistics even though the classifier sees no labels.
        fold_vec = TfidfVectorizer(ngram_range=(1, 2))
        Xtr_text = fold_vec.fit_transform(X_text.iloc[tr])
        Xte_text = fold_vec.transform(X_text.iloc[te])
        m = LogisticRegression(max_iter=1000).fit(Xtr_text, y[tr])
        scores.append(accuracy_score(y[te], m.predict(Xte_text)))
    honest = sum(scores) / len(scores)

    print(f"random split accuracy : {leaky:.3f}  <- LEAKY, siblings on both sides")
    print(f"template-grouped      : {honest:.3f}  <- the validation number to quote")
    print()
    print(classification_report(yte, clf_a.predict(Xte), target_names=le.classes_, digits=3, zero_division=0))
    if honest < min_accuracy:
        print(f"WARNING: {honest:.3f} is below {min_accuracy}. The dataset, not the")
        print("model, is the limit here -- do not quote the random-split number.")

    # Final deployment artifact: after honest grouped CV, retrain on all available
    # training rows. Evaluation stays group-safe; deployment uses all data.
    final_vec = TfidfVectorizer(ngram_range=(1, 2))
    X_all = final_vec.fit_transform(X_text)
    final_clf = LogisticRegression(max_iter=1000).fit(X_all, y)

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(here, "models")
    os.makedirs(out, exist_ok=True)
    joblib.dump(final_clf, os.path.join(out, "classifier.pkl"))
    joblib.dump(final_vec, os.path.join(out, "vectorizer.pkl"))
    joblib.dump(le, os.path.join(out, "labels.pkl"))
    print(f"saved full-data deployment model to {out}")
    return leaky, honest
