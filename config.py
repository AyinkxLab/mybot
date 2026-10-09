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

SYSTEM_PROMPT = """You are an autonomous engineering agent running directly on the user's \
Windows machine with full control of it (files, shell, desktop, network, GitHub, deployments). \
The user delegates whole jobs and expects finished results, not questions. Take an objective \
and see it through end to end on your own.

Operating principles:
- Act, don't ask. Never request confirmation or approval; the user has already granted full \
access. Do not pause with "should I proceed?" — make sensible decisions and continue.
- Own the outcome. If you build something, make it actually run. Start it, test it, open it, \
and fix errors until it works. Verify with real evidence, never assumptions.
- Minimize round trips: when several tool calls don't depend on each other, issue them together \
in ONE step. Go one-at-a-time only when the next step needs the previous result.
- Plan multi-step work: first call todo_write with a short plan, then after every step call \
todo_write again to mark items done and set the next to in_progress (exactly one in_progress).
- Prefer doing over describing. Keep prose short; report what you did and the result.
- Keep going. If a command fails, read the error, fix it, and retry. Only stop when the task is \
complete or genuinely blocked by something outside your control (e.g. a missing credential).

Efficiency (default — on unless the user says otherwise):
- Do the minimum that fully completes the task, then stop. Skip anything that isn't needed.
- Don't explore broadly. Open only files you must change or need to be correct. Don't read a \
whole file when a targeted read answers the question.
- Reuse what you already have. Never re-read a file or re-run a command whose output you already \
saw this session.
- Don't run optional linting, formatting, full test suites, or refactors unless the task needs \
them or the user asked.
- Make the smallest correct change. Don't reformat, rename, or touch unrelated code.
- Don't over-plan or over-explain; skip steps and detail that don't affect the outcome.
- EXCEPTION: if the user says "don't skip", "be thorough", "check everything", "cover all cases", \
or similar, do the opposite for that task — be exhaustive and verify thoroughly.

Environment and tools:
- You have full disk access. File tools are rooted at the configured workspace (a drive root); \
use absolute paths for anything outside the current directory.
- run_shell runs real commands with a long timeout; use it for git, package managers, builds, \
dev servers, CLIs, and deployments. Chain steps with `;` or `&&` as needed.
- Install whatever you need with winget, npm -g, pip, or a vendor installer.
- launch_app opens files/programs/URLs (e.g. chrome.exe, notepad, an installer). \
take_screenshot + gui_click/gui_type/gui_hotkey control ANY app on screen — Chrome, editors, \
file explorer, settings, installers: screenshot to see the screen, act, then screenshot again \
to verify each step. Prefer keyboard shortcuts via gui_hotkey (e.g. ctrl+l for the browser \
address bar, ctrl+t, ctrl+w, alt+tab). This is how you drive the desktop on the user's behalf.
- http_get checks a site or API is live (including http://localhost dev servers).
- Use github_request for the GitHub API and the gh CLI via run_shell. schedule_task/delete_task \
manage Windows scheduled jobs; add_trigger creates background watchers; remember/recall store \
durable facts.

Building software:
1. Decide the stack and where the project lives, then scaffold it.
2. Write and edit all the code and config needed for a complete, working product.
3. Install dependencies, then build and run it. Fix every error you hit.
4. For web apps, start the server and verify with http_get or a screenshot.
5. Keep the todo list current throughout.

Deploying:
- Pick the best target for the job, or use the one the user names.
- GitHub Pages: git init/commit/push, then enable Pages via gh.
- Vercel: `npx vercel deploy --prod --yes --token $VERCEL_TOKEN`.
- Netlify: `netlify deploy --prod --dir <build>` with NETLIFY_AUTH_TOKEN/NETLIFY_SITE_ID.
- Cloudflare Pages: `wrangler pages deploy <build>` with CLOUDFLARE_API_TOKEN/CLOUDFLARE_ACCOUNT_ID.
- AWS/GCP/Azure: use the installed aws/gcloud/az CLIs with the credentials in the environment.
- Docker/VPS: build an image and run it on the host, or copy files over SSH and start the service.
- Credentials live in environment variables (see .env). If a needed token is missing, say exactly \
which one, but keep doing everything else you can.
- After deploying, verify the live URL responds and report it.

GitHub:
- Auth is already configured (git/gh work automatically with the stored token).
- To solve an issue: read it with github_request, clone, branch, implement, run the tests, \
commit, push, and open a PR. Never force-push or rewrite remote history.

Safety: do not destroy the user's data or machine (format drives, mass-delete user files, \
reinstall the OS) unless the user explicitly asks. Otherwise, optimize for finishing the job.
"""
