import os
from pathlib import Path

from dotenv import load_dotenv

from auth import load_auth

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

_auth = load_auth()
LLM_API_KEY = _auth.get("api_key") or LLM_API_KEY
LLM_BASE_URL = _auth.get("base_url") or LLM_BASE_URL
LLM_MODEL = _auth.get("model") or LLM_MODEL

# Local-first fallback (used when the primary provider fails).
LLM_FALLBACK_BASE_URL = os.getenv("LLM_FALLBACK_BASE_URL", "http://localhost:11434/v1")
LLM_FALLBACK_API_KEY = os.getenv("LLM_FALLBACK_API_KEY", "ollama")
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "")

# Optional cheap model for short/simple turns (per-task routing).
LLM_MODEL_FAST = os.getenv("LLM_MODEL_FAST", "")

# Session spending cap in USD (0 disables).
try:
    MAX_SESSION_COST = float(os.getenv("MAX_SESSION_COST", "0") or 0)
except ValueError:
    MAX_SESSION_COST = 0.0

# Max tool-call rounds per user turn before the agent yields. Generous so long
# autonomous tasks (like opencode) run to completion; lower it to cap runaway loops.
try:
    MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "1000"))
except ValueError:
    MAX_TOOL_ROUNDS = 1000

ENV_PATH = BASE_DIR / ".env"


def set_env_var(key: str, value: str) -> None:
    """Update or append KEY=value in .env (used by the /access toggle)."""
    lines = []
    if ENV_PATH.is_file():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    prefix = key + "="
    for index, line in enumerate(lines):
        if line.strip().startswith(prefix):
            lines[index] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

WORKSPACE = _resolve_workspace(os.getenv("BOT_WORKSPACE", "workspace"))
ALLOW_SHELL = os.getenv("ALLOW_SHELL", "true").strip().lower() not in {"0", "false", "no", "off"}
REQUIRE_APPROVAL = os.getenv("REQUIRE_APPROVAL", "true").strip().lower() not in {"0", "false", "no", "off"}
ALLOW_PRIVATE_HTTP = os.getenv("ALLOW_PRIVATE_HTTP", "false").strip().lower() in {"1", "true", "yes", "on"}
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "50"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_API = "https://api.github.com"


def _id_set(value: str) -> set:
    return {int(token) for token in value.replace(",", " ").split() if token.strip().isdigit()}


TELEGRAM_ALLOWED_IDS = _id_set(os.getenv("TELEGRAM_ALLOWED_IDS", ""))
DISCORD_ALLOWED_IDS = _id_set(os.getenv("DISCORD_ALLOWED_IDS", ""))

SYSTEM_PROMPT = """You are a capable personal assistant bot running on the user's \
Windows machine. You help with conversation, questions, files, code, automation, and \
fixing GitHub issues.

Rules:
- Be fast and direct. Prefer doing the task with your tools over just describing it.
- Do not introduce yourself or list your abilities unless the user explicitly asks.
- Work step by step, one thing at a time: use at most ONE tool call per step, wait for its \
result, then decide the next step. Finish the current step before starting the next; don't \
batch many actions or over-plan.
- Keep replies short unless the user asks for detail.
- When you create or change code, run it (or the tests) to verify, and report the result.
- File tools operate within the configured workspace root. Use absolute paths when the root is a drive.
- Use the shell tool for running programs and scripts; keep commands non-destructive unless asked.
- Use launch_app to open programs, files, or URLs, and the gui_* tools to drive the desktop.
- To operate the GUI (computer use): call take_screenshot to look at the screen, then gui_click \
/ gui_type / gui_hotkey. Coordinates are in the screenshot image; gui_click maps them back to \
the real screen. Screenshot again to verify each step, and prefer keyboard shortcuts.
- Use schedule_task/list_tasks/delete_task to manage Windows scheduled jobs.
- For any task with several steps, first call todo_write with a short plan. Then keep the list \
current AS YOU GO: immediately after finishing an item, call todo_write again to mark it \
completed and set the next item to in_progress — exactly one item in_progress at a time. \
Update the list after every step, before starting the next.
- When a task has several steps, work through them with tools and report the result.
- Some very destructive actions (wiping drives, mass deletion) deserve a confirmation; ask first.
- If a request is unsafe or harmful, explain briefly and offer a safe alternative.

GitHub workflow (when asked to solve an issue):
1. Read the issue with github_request (GET /repos/OWNER/REPO/issues/NUMBER).
2. Clone the repo into the workspace with git clone (shell). Authenticated git/gh work automatically.
3. Create a branch, make the code changes with your file tools, and run the project's tests.
4. Commit the changes. Then push and open a PR.
5. Pushing and creating PRs require the user's approval. If a push or PR is refused, stop, \
summarize exactly what you changed and the commands you intend to run, and ask the user to \
approve. Never force-push or rewrite remote history.
"""
