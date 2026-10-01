"""Small task-aware model router with environment-configurable fallbacks."""

from __future__ import annotations

import os


def model_for(task: str) -> str:
    defaults = {
        "triage": os.getenv("OLLAMA_MODEL", "qwen3.5:9b"),
        "coding": os.getenv("OLLAMA_CODING_MODEL", os.getenv("OLLAMA_MODEL", "qwen3.5:9b")),
        "review": os.getenv("OLLAMA_REVIEW_MODEL", os.getenv("OLLAMA_MODEL", "qwen3.5:9b")),
    }
    return defaults.get(task, defaults["coding"])