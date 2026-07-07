import os
import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from sklearn.preprocessing import LabelEncoder
from sentence_transformers import SentenceTransformer

from src.config import ML_CONFIDENCE_THRESHOLD

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models")
MODEL_PATH = os.path.join(MODEL_DIR, "classifier.pkl")
ENCODER_PATH = os.path.join(MODEL_DIR, "label_encoder.pkl")

_embedder = SentenceTransformer("all-MiniLM-L6-v2")


def train_model():
    os.makedirs(MODEL_DIR, exist_ok=True)
    df = pd.read_csv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sample_logs.csv"))

    X = _embedder.encode(df["log_text"].tolist(), show_progress_bar=True)
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
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError("Run train_model() first")

    clf = joblib.load(MODEL_PATH)
    le = joblib.load(ENCODER_PATH)

    emb = _embedder.encode([text])
    probs = clf.predict_proba(emb)[0]
    best_idx = probs.argmax()
    confidence = float(probs[best_idx])
    category = le.classes_[best_idx]

    if confidence >= ML_CONFIDENCE_THRESHOLD:
        return category, confidence
    return None, confidence
