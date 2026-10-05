import json
import os
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
AUTH_PATH = BASE_DIR / ".mybot_config.json"

PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-flash", "deepseek-v4-pro"],
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
