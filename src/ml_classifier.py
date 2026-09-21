"""Simple ML tier using TF-IDF + Logistic Regression."""
import os
import joblib
from src.config import ML_CONFIDENCE_THRESHOLD

ROOT = os.path.dirname(os.path.dirname(__file__))
MODEL_DIR = os.path.join(ROOT, "models")
MODEL_PATH = os.path.join(MODEL_DIR, "classifier.pkl")
VECTORIZER_PATH = os.path.join(MODEL_DIR, "vectorizer.pkl")
ENCODER_PATH = os.path.join(MODEL_DIR, "label_encoder.pkl")

_clf = None
_vectorizer = None
_le = None


def _load_artifacts():
    global _clf, _vectorizer, _le
    if not all(os.path.exists(p) for p in [MODEL_PATH, VECTORIZER_PATH, ENCODER_PATH]):
        return None
    if _clf is None:
        _clf = joblib.load(MODEL_PATH)
        _vectorizer = joblib.load(VECTORIZER_PATH)
        _le = joblib.load(ENCODER_PATH)
    return _clf, _vectorizer, _le


def train_model():
    import pandas as pd
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import classification_report
    from sklearn.preprocessing import LabelEncoder
    from sklearn.feature_extraction.text import TfidfVectorizer

    df = pd.read_csv(os.path.join(ROOT, "data", "sample_logs.csv"))
    vectorizer = TfidfVectorizer(lowercase=True, ngram_range=(1, 2))
    X = vectorizer.fit_transform(df["log_text"].astype(str))

    le = LabelEncoder()
    y = le.fit_transform(df["category"])

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    clf = LogisticRegression(max_iter=1000)
    clf.fit(X_train, y_train)

    print(classification_report(
        y_test, clf.predict(X_test), target_names=le.classes_, digits=4
    ))

    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(clf, MODEL_PATH)
    joblib.dump(vectorizer, VECTORIZER_PATH)
    joblib.dump(le, ENCODER_PATH)
    print("ML model trained and saved.")


def classify_ml(text: str):
    try:
        artifacts = _load_artifacts()
        if artifacts is None:
            return None, 0.0

        clf, vectorizer, le = artifacts
        probs = clf.predict_proba(vectorizer.transform([text]))[0]
        best_idx = probs.argmax()
        confidence = float(probs[best_idx])
        category = le.classes_[best_idx]

        if confidence >= ML_CONFIDENCE_THRESHOLD:
            return category, confidence
        return None, confidence
    except Exception:
        return None, 0.0
