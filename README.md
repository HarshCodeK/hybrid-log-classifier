# Hybrid Log Classifier

A small, runnable log-classification project: **Regex → scikit-learn ML → optional Groq LLM**. A FastAPI endpoint and Streamlit page use the same classifier. Results and classification latency are stored in SQLite.

## Requirements

- Python 3.11 or newer
- Internet access and a Groq API key only if you want the LLM fallback

## Windows setup (PowerShell)

Clone the repository, then run these commands from its folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Open `.env` and optionally add your Groq key to `GROQ_API_KEY=`. You can skip this; Regex and ML still work.

## Start the project

Open **two PowerShell terminals** in the project folder. Activate the environment in each terminal.

**Terminal 1 — API**

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn hybrid_log_classifier.api:app --reload
```

**Terminal 2 — Streamlit interface**

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

Open the Streamlit URL shown in the terminal (usually http://localhost:8501). API docs: http://127.0.0.1:8000/docs.

## Test the API

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/classify -ContentType "application/json" -Body '{"text":"failed login user=demo"}'
```

Check health at http://127.0.0.1:8000/health.

## How classification works

1. **Regex:** known, obvious patterns are classified immediately.
2. **ML:** a small TF-IDF + Logistic Regression model trained from `data/training.csv` handles other log wording.
3. **Groq:** if ML confidence is below `ML_CONFIDENCE_THRESHOLD`, Groq is tried when `GROQ_API_KEY` is set. If it is not configured or fails, the result is `unknown` rather than a made-up answer.

The training dataset is a small demonstration dataset, not a production-quality model. Classification latency and output are written to `runtime/classifications.db`.

## Troubleshooting

- **`uvicorn is not recognized`:** activate `.venv` and run `python -m uvicorn hybrid_log_classifier.api:app --reload`.
- **`No module named hybrid_log_classifier`:** run the command from the repository root and confirm `pip install -r requirements.txt` completed.
- **Port 8000 is already in use:** stop the process using it, or run `python -m uvicorn hybrid_log_classifier.api:app --reload --port 8001`.
- **Groq errors:** check the key, internet connection, model name, and account limits. The app should still classify with Regex/ML and return `unknown` if it cannot confidently classify.
- **PowerShell blocks activation:** run `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` and launch using `.\.venv\Scripts\python.exe -m uvicorn hybrid_log_classifier.api:app --reload`; activation is optional.

## Run tests

```powershell
python -m pytest
```

## Safety note

Use synthetic or de-identified logs. This demo has no authentication and stores submitted log text in a local SQLite database; do not expose it publicly with sensitive logs.
