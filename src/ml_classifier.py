"""ML tier: LogisticRegression over sentence-transformer embeddings.

Lazy-loads the embedder and the trained artifacts so the API/UI can boot
without the heavy dependencies present, and falls through to the next tier
when the model isn't trained or the libs aren't installed.
"""
import os
import joblib
from src.config import ML_CONFIDENCE_THRESHOLD

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models")
MODEL_PATH = os.path.join(MODEL_DIR, "classifier.pkl")
ENCODER_PATH = os.path.join(MODEL_DIR, "label_encoder.pkl")

_embedder = None
_clf = None
_le = None


def _get_embedder():
    # Lazy import: sentence-transformers pulls in torch (~2.5GB). Skipping it
    # lets regex + LLM tiers work in minimal installs, and tests run offline.
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder


def _load_artifacts():
    # Cache the pickles once instead of re-reading from disk every call.
    global _clf, _le
    if _clf is None:
        if not (os.path.exists(MODEL_PATH) and os.path.exists(ENCODER_PATH)):
            return None
        _clf = joblib.load(MODEL_PATH)
        _le = joblib.load(ENCODER_PATH)
    return _clf, _le


def train_model():
    import pandas as pd
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import classification_report
    from sklearn.preprocessing import LabelEncoder

    os.makedirs(MODEL_DIR, exist_ok=True)
    df = pd.read_csv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sample_logs.csv"))

    X = _get_embedder().encode(df["log_text"].tolist(), show_progress_bar=True)
    y = df["category"].values

    le = LabelEncoder()
    y_encoded = le.fit_transform(y)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y_encoded, test_size=0.2, random_state=42, stratify=y_encoded
    )

    clf = LogisticRegression(max_iter=1000)
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    print(classification_report(y_test, y_pred, target_names=le.classes_, digits=4))

    joblib.dump(clf, MODEL_PATH)
    joblib.dump(le, ENCODER_PATH)
    print(f"Model saved to {MODEL_PATH}")


def classify_ml(text: str):
    """Return (category, confidence) if confident, else (None, confidence_or_0).

    Never raises for missing model/libs — the pipeline falls through to the
    LLM tier instead of crashing the request.
    """
    artifacts = _load_artifacts()
    if artifacts is None:
        return None, 0.0  # model not trained yet -> next tier decides

    clf, le = artifacts
    try:
        emb = _get_embedder().encode([text])
    except ImportError:
        return None, 0.0  # sentence-transformers not installed -> next tier

    probs = clf.predict_proba(emb)[0]
    best_idx = probs.argmax()
    confidence = float(probs[best_idx])
    category = le.classes_[best_idx]

    if confidence >= ML_CONFIDENCE_THRESHOLD:
        return category, confidence
    return None, confidence
