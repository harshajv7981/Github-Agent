"""Small task-aware model router with environment-configurable fallbacks."""

from __future__ import annotations

import os


def provider_name() -> str:
    return os.getenv("LLM_PROVIDER", "ollama").strip().lower()


def model_for(task: str) -> str:
    provider = provider_name()
    if provider == "openrouter":
        default_model = os.getenv(
            "OPENROUTER_MODEL",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
        )
        task_models = {
            "triage": os.getenv("OPENROUTER_TRIAGE_MODEL", default_model),
            "coding": os.getenv("OPENROUTER_CODING_MODEL", default_model),
            "review": os.getenv("OPENROUTER_REVIEW_MODEL", default_model),
        }
        return task_models.get(task, task_models["coding"])

    if provider == "groq":
        default_model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
        task_models = {
            "triage": os.getenv("GROQ_TRIAGE_MODEL", default_model),
            "coding": os.getenv("GROQ_CODING_MODEL", default_model),
            "review": os.getenv("GROQ_REVIEW_MODEL", default_model),
        }
        return task_models.get(task, task_models["coding"])

    defaults = {
        "triage": os.getenv("OLLAMA_MODEL", "qwen3.5:9b"),
        "coding": os.getenv("OLLAMA_CODING_MODEL", os.getenv("OLLAMA_MODEL", "qwen3.5:9b")),
        "review": os.getenv("OLLAMA_REVIEW_MODEL", os.getenv("OLLAMA_MODEL", "qwen3.5:9b")),
    }
    return defaults.get(task, defaults["coding"])