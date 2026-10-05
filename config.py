import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


def _resolve_workspace(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

WORKSPACE = _resolve_workspace(os.getenv("BOT_WORKSPACE", "workspace"))
ALLOW_SHELL = os.getenv("ALLOW_SHELL", "true").strip().lower() not in {"0", "false", "no", "off"}

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

SYSTEM_PROMPT = """You are a capable personal assistant bot running on the user's \
Windows machine. You help with conversation, questions, files, code, and automation.

Rules:
- Be direct and concise. Prefer doing the task with your tools over just describing it.
- All file paths for file tools are relative to the bot workspace. Do not try to escape it.
- Use the shell tool for running programs and scripts; keep commands non-destructive unless asked.
- When a task has several steps, work through them with tools and report the result.
- If a request is unsafe or harmful, explain briefly and offer a safe alternative.
"""
