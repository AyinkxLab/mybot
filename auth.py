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
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "models": ["deepseek/deepseek-chat", "anthropic/claude-3.5-sonnet"],
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama-3.3-70b-versatile"],
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "models": ["llama3.1", "qwen2.5"],
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
}


def model_label(model: str) -> str:
    return MODEL_LABELS.get(model, model)


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
    if text.startswith(("sk-", "sk_", "gsk_", "xai-", "or-", "r8_")):
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
