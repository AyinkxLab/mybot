import json
import os
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
AUTH_PATH = BASE_DIR / ".mybot_config.json"

PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "models": [
            "deepseek-flash",
            "deepseek-v4-pro",
            "deepseek-v4-flash",
            "deepseek-v4-flash-vision-exp",
            "deepseek-chat",
            "deepseek-reasoner",
        ],
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1", "gpt-4.1-mini"],
    },
    "google": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "models": [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
        ],
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "models": [
            "qwen/qwen2.5-vl-72b-instruct:free",
            "meta-llama/llama-4-scout:free",
            "meta-llama/llama-4-maverick:free",
            "google/gemini-2.0-flash-exp:free",
            "mistralai/mistral-small-3.1-24b-instruct:free",
            "deepseek/deepseek-r1:free",
            "deepseek/deepseek-chat",
            "anthropic/claude-3.5-sonnet",
        ],
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "models": [
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "meta-llama/llama-4-maverick-17b-128e-instruct",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
        ],
    },
    "github": {
        "base_url": "https://models.inference.ai.azure.com",
        "models": [
            "gpt-4o",
            "gpt-4o-mini",
            "meta/Llama-4-Scout-17B-16E-Instruct",
            "mistral-ai/Pixtral-Large-Instruct-2411",
        ],
    },
    "cerebras": {
        "base_url": "https://api.cerebras.ai/v1",
        "models": ["llama-4-scout-17b-16e-instruct", "llama3.1-8b"],
    },
    "huggingface": {
        "base_url": "https://router.huggingface.co/v1",
        "models": [
            "Qwen/Qwen2.5-VL-72B-Instruct",
            "meta-llama/Llama-4-Scout-17B-16E-Instruct",
        ],
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "models": ["pixtral-large-latest", "mistral-small-latest", "pixtral-12b-2409"],
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "models": ["qwen2.5vl:7b", "llama3.2-vision", "llava", "moondream", "llama3.1"],
    },
}


MODEL_LABELS = {
    "deepseek-flash": "DeepSeek V4.1 Flash",
    "deepseek-v4-pro": "DeepSeek V4 Pro",
    "deepseek-v4-flash": "DeepSeek V4 Flash (legacy)",
    "deepseek-v4-flash-vision-exp": "DeepSeek V4 Flash Vision (legacy)",
    "deepseek-chat": "DeepSeek Chat",
    "deepseek-reasoner": "DeepSeek Reasoner",
    "gpt-4o-mini": "GPT-4o mini",
    "gpt-4o": "GPT-4o",
    "gpt-4.1": "GPT-4.1",
    "gpt-4.1-mini": "GPT-4.1 mini",
    "llama-3.3-70b-versatile": "Llama 3.3 70B",
    "gemini-2.5-flash": "Gemini 2.5 Flash (vision, free)",
    "gemini-2.5-pro": "Gemini 2.5 Pro (vision, free tier)",
    "gemini-2.0-flash": "Gemini 2.0 Flash (vision, free)",
    "gemini-2.0-flash-lite": "Gemini 2.0 Flash Lite (free)",
    "qwen/qwen2.5-vl-72b-instruct:free": "Qwen2.5-VL 72B (vision, free)",
    "meta-llama/llama-4-scout:free": "Llama 4 Scout (vision, free)",
    "meta-llama/llama-4-scout-17b-16e-instruct": "Llama 4 Scout (vision)",
    "meta-llama/llama-4-maverick:free": "Llama 4 Maverick (vision, free)",
    "meta-llama/llama-4-maverick-17b-128e-instruct": "Llama 4 Maverick (vision)",
    "google/gemini-2.0-flash-exp:free": "Gemini 2.0 Flash Exp (vision, free)",
    "mistralai/mistral-small-3.1-24b-instruct:free": "Mistral Small 3.1 (vision, free)",
    "deepseek/deepseek-r1:free": "DeepSeek R1 (free)",
    "qwen2.5vl:7b": "Qwen2.5-VL 7B (local, vision)",
    "llama3.2-vision": "Llama 3.2 Vision (local)",
    "llava": "LLaVA (local, vision)",
    "moondream": "Moondream (local, vision)",
    "pixtral-large-latest": "Pixtral Large (vision)",
    "mistral-small-latest": "Mistral Small",
}


def model_label(model: str) -> str:
    return MODEL_LABELS.get(model, model)


PROVIDER_LABELS = {
    "deepseek": "DeepSeek",
    "openai": "OpenAI",
    "google": "Google",
    "openrouter": "OpenRouter",
    "groq": "Groq",
    "github": "GitHub",
    "cerebras": "Cerebras",
    "huggingface": "Hugging Face",
    "mistral": "Mistral",
    "ollama": "Ollama",
}


def provider_label(provider: str) -> str:
    return PROVIDER_LABELS.get(provider, provider.capitalize() if provider else "")


def load_auth() -> dict:
    if AUTH_PATH.is_file():
        try:
            return json.loads(AUTH_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_auth(data: dict) -> None:
    AUTH_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_configured() -> bool:
    return bool(load_auth().get("api_key") or os.getenv("LLM_API_KEY"))


def looks_like_api_key(value: str) -> bool:
    text = value.strip()
    if not text or " " in text or text in PROVIDERS:
        return False
    if text.startswith(
        ("sk-", "sk_", "gsk_", "xai-", "or-", "r8_", "AIza", "hf_", "csk-", "ghp_", "github_pat_")
    ):
        return True
    return len(text) >= 32 and any(c.isdigit() for c in text) and any(c.isalpha() for c in text)


def list_models(base_url: str, api_key: str) -> list:
    """Ask the provider which models this key can use. Empty list on failure."""
    try:
        resp = requests.get(
            base_url.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return [item["id"] for item in data if isinstance(item, dict) and item.get("id")]
    except Exception:
        return []
