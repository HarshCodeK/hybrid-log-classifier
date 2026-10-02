"""Which models exist, and what they cost.

One file, because a model name hardcoded anywhere else is a bug waiting to
happen. Groq retires models without a deprecation warning -- an outdated id
returns a hard 404 -- so every model used anywhere in this project is named
here and nowhere else.

Checked live on 2026-10-03 via GET /models with this project's key:
`llama-3.3-70b-versatile` and `llama-3.1-8b-instant` return 404 on this
account, and `qwen/qwen3.8-27b` is still callable but flagged preview.
"""

# id: (label, input $/1M, output $/1M, usable)
MODELS = {
    # usable=True means this account can actually serve it (tested 2026-10-03).
    "openai/gpt-oss-120b": ("GPT-OSS 120B", 0.15, 0.60, True),
    "openai/gpt-oss-20b": ("GPT-OSS 20B", 0.075, 0.30, True),
    "qwen/qwen3.8-27b": ("Qwen 3.8 27B (preview)", 0.80, 4.00, True),
    "allam-2-7b": ("ALLaM 2 7B", 0.30, 0.30, True),
    # listed by Groq docs but 404 on this account:
    "llama-3.3-70b-versatile": ("Llama 3.3 70B", 0.0, 0.0, False),
    "llama-3.1-8b-instant": ("Llama 3.1 8B", 0.0, 0.0, False),
}

DEFAULT_MODEL = "openai/gpt-oss-120b"


class UnknownModel(ValueError):
    """A model id that is not in the table above."""


def resolve(model_id: str = None) -> str:
    """Return a model id that is known to exist."""
    candidate = model_id or DEFAULT_MODEL
    if candidate not in MODELS:
        raise UnknownModel(
            f"{candidate!r} is not a known model. Available: {', '.join(MODELS)}"
        )
    if not MODELS[candidate][3]:
        raise UnknownModel(
            f"{candidate!r} is not servable on this account (tested 2026-10-03). "
            f"Usable: {[m for m, v in MODELS.items() if v[3]]}"
        )
    return candidate


def estimate_cost_usd(model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Rough cost. Unknown models are refused rather than guessed at."""
    _, per_in, per_out, _ok = MODELS[resolve(model_id)]
    return (prompt_tokens * per_in + completion_tokens * per_out) / 1_000_000
