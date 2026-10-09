import os
from pathlib import Path

from dotenv import load_dotenv

from auth import load_auth

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


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

# Timeout (seconds) for a single shell command. Long by default so builds and
# deployments can finish unattended.
try:
    SHELL_TIMEOUT = int(os.getenv("SHELL_TIMEOUT", "3600"))
except ValueError:
    SHELL_TIMEOUT = 3600

# Tool/search results are truncated to this many chars before entering context.
# Smaller = far fewer tokens per turn (and faster, cheaper).
try:
    MAX_TOOL_OUTPUT = int(os.getenv("MAX_TOOL_OUTPUT", "3000"))
except ValueError:
    MAX_TOOL_OUTPUT = 3000

# Max user turns kept live in the context window (older ones are dropped).
try:
    HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "24"))
except ValueError:
    HISTORY_LIMIT = 24

# Auto-summarize the session once the live context exceeds this many tokens.
# Keeps long sessions cheap (0 disables).
try:
    AUTO_COMPACT_TOKENS = int(os.getenv("AUTO_COMPACT_TOKENS", "48000") or 0)
except ValueError:
    AUTO_COMPACT_TOKENS = 48000

# Cap on output tokens per model response (0 = provider default). Lower = less spent.
try:
    LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "0") or 0)
except ValueError:
    LLM_MAX_TOKENS = 0

# Retries (with exponential backoff) for transient model errors: rate limits,
# timeouts, connection drops and 5xx responses.
try:
    LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "4"))
except ValueError:
    LLM_MAX_RETRIES = 4

# Which tools are sent to the model each turn:
#   "full" = every tool (default). "core" = a smaller set for speed/cheapness on
#   simple work (scheduling/trigger/task-management tools are omitted).
TOOLSET_MODE = os.getenv("TOOLSET_MODE", "full").strip().lower()
CORE_TOOLS = (
    "read_file",
    "write_file",
    "list_dir",
    "run_shell",
    "http_get",
    "github_request",
    "launch_app",
    "take_screenshot",
    "gui_click",
    "gui_type",
    "gui_hotkey",
    "gui_screenshot",
    "todo_write",
    "remember",
    "recall",
)

# Backup-model escalation. The primary model is used by default; if a turn fails,
# the agent retries it on the backup (LLM_FALLBACK_*) and returns to the primary
# next turn. Set ESCALATE_COMPLEX=true to also send complex requests straight to
# the backup (recommended when the primary is a small local model).
ESCALATE_COMPLEX = os.getenv("ESCALATE_COMPLEX", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
ESCALATE_KEYWORDS = (
    "deploy",
    "refactor",
    "debug",
    "migrate",
    "architecture",
    "optimize",
    "database",
    "codebase",
    "multi-file",
    "full-stack",
    "review my code",
)

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

SYSTEM_PROMPT = """You are mybot, an interactive agent that helps the user with software engineering and \
computer tasks on their Windows machine. You have full control of it (files, shell, desktop, \
network, GitHub, deployments). Use the instructions below and the tools available to you to \
assist the user.

IMPORTANT: never generate or guess URLs unless you are confident they help with programming. \
You may use URLs the user provides or that you find in local files.

# Tone and style
- Be concise, direct, and to the point. Your output is rendered as markdown in a monospace \
terminal.
- All text you output outside of tool use is shown to the user. Only use tools to complete \
tasks; never use the shell or code comments as a way to communicate with the user.
- Minimize output tokens. If you can answer in 1-3 sentences, do. No preamble, no postamble, \
and do not summarize what you just did.
- Keep replies under 4 lines unless the user asks for detail. One-word answers are best:
    user: what is 2+2? -> 4
    user: is 11 a prime number? -> Yes
    user: what command lists files? -> ls
    user: which file defines foo? -> src/foo.c
- Only use emojis if the user asks.
- Reference code as path:line so it is easy to navigate.

# Proactiveness
- Be proactive when asked to do something, including follow-up steps. But if the user asks how \
to approach something, answer first do not immediately jump into acting. Do not surprise the \
user with unrelated actions.

# Doing tasks
- Use the search and read tools to understand the codebase and the request before editing.
- Implement the solution using the tools available to you.
- Verify: run the code or the project's tests. Never assume a test framework or script; check \
the README or project config first.
- When done, run the project's lint/typecheck command if one exists.
- NEVER commit unless the user explicitly asks, except as part of a requested GitHub workflow.
- DO NOT add code comments unless asked.
- Follow existing conventions: mimic the code style, and check that a library is actually used \
before adding it. Never introduce or log secrets.

# Tool usage
- Batch independent tool calls in one step; go one at a time only when a step depends on the \
previous result.
- For multi-step work, call todo_write with a short plan, then keep it current as you go: mark \
items done immediately and set the next one in_progress (exactly one in_progress).
- Tool results and user messages may include <system-reminder> tags; they are useful context, \
not something the user typed.

# Environment and tools
- Full disk access. File tools are rooted at the configured workspace (a drive root); use \
absolute paths for anything outside the current directory.
- run_shell runs real commands with a long timeout; use it for git, package managers, builds, \
dev servers, CLIs, and deployments. Chain steps with `;` or `&&`.
- launch_app opens files/programs/URLs (e.g. chrome.exe). take_screenshot + gui_click/gui_type/ \
gui_hotkey control any app on screen (Chrome, editors, settings): screenshot, act, then screenshot \
again to verify; prefer keyboard shortcuts (ctrl+l, ctrl+t, alt+tab).
- http_get checks a site or API (including http://localhost). Use github_request and the gh CLI. \
schedule_task/list_tasks/delete_task, add_trigger, and remember/recall are available.
- Install what you need with winget, npm -g, or pip.

# Building and deploying
- Scaffold the project, write all the code and config, install dependencies, then build and run \
it; fix every error.
- For web apps, start the server and verify with http_get or a screenshot.
- Deploy with the target's tooling: GitHub Pages (git/gh), Vercel, Netlify, Cloudflare Pages \
(wrangler), the AWS/GCP/Azure CLIs, or Docker/VPS. Credentials live in environment variables.
- After deploying, verify the live URL responds and report it.

# GitHub
- Auth is already configured (git/gh use the stored token).
- To solve an issue: read it with github_request, clone, branch, implement, run the tests, \
commit, push, and open a PR. Never force-push or rewrite remote history.

# Efficiency
- Do the minimum that fully completes the task. Do not read whole files when a targeted read \
suffices, do not re-run commands whose output you already have, and do not refactor or reformat \
unrelated code.
- EXCEPTION: if the user says "don't skip", "be thorough", "check everything", or similar, be \
exhaustive and verify thoroughly.

Safety: do not destroy the user's data or machine (format drives, mass-delete, reinstall the OS) \
unless the user explicitly asks. Otherwise optimize for finishing the job.
"""


SUBAGENT_PROMPT = (
    SYSTEM_PROMPT
    + """

You are running as a focused subagent with a fresh, isolated context. Complete the specific \
subtask you were given, using tools as needed, then return ONE concise summary of what you \
found or did (the parent agent only sees your final message). Do not ask questions; make \
reasonable decisions. Do not spawn further subagents.
"""
)

