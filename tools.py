import difflib
import ipaddress
import json
import os
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import requests

from config import (
    ALLOW_PRIVATE_HTTP,
    ALLOW_SHELL,
    GITHUB_API,
    GITHUB_TOKEN,
    REQUIRE_APPROVAL,
    WORKSPACE,
)

MAX_OUTPUT = 8000

_approval_handler = None


def set_approval_handler(handler) -> None:
    global _approval_handler
    _approval_handler = handler


def _ask_approval(action: str) -> bool:
    if _approval_handler is None:
        return False
    return bool(_approval_handler(action))


def _shell_env() -> dict:
    env = os.environ.copy()
    if GITHUB_TOKEN:
        env["GITHUB_TOKEN"] = GITHUB_TOKEN
        env["GH_TOKEN"] = GITHUB_TOKEN
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    return env


DESTRUCTIVE_SHELL_PATTERNS = (
    "git push",
    "git.exe push",
    "gh pr create",
    "gh release",
    "gh repo delete",
    "gh api --method post",
    "gh api --method patch",
    "gh api --method delete",
    "gh api -x post",
    "gh api -x patch",
    "gh api -x delete",
)


def _normalize_command(command: str) -> str:
    cleaned = command.lower().replace('"', " ").replace("'", " ")
    return " ".join(cleaned.split())


def _is_destructive(command: str) -> bool:
    normalized = _normalize_command(command)
    if any(pattern in normalized for pattern in DESTRUCTIVE_SHELL_PATTERNS):
        return True
    tokens = normalized.split()
    if "push" in tokens and any(token in {"git", "git.exe"} for token in tokens):
        return True
    return False


def _safe_path(relative: str) -> Path:
    target = (WORKSPACE / relative).resolve()
    if WORKSPACE != target and WORKSPACE not in target.parents:
        raise ValueError(f"Path escapes workspace: {relative}")
    return target


def _truncate(text: str) -> str:
    if len(text) > MAX_OUTPUT:
        return text[:MAX_OUTPUT] + f"\n...[truncated {len(text) - MAX_OUTPUT} chars]"
    return text


_snapshot: dict = {}
_snapshot_active = False


def begin_snapshot() -> None:
    global _snapshot, _snapshot_active
    _snapshot = {}
    _snapshot_active = True


def end_snapshot() -> dict:
    global _snapshot_active
    _snapshot_active = False
    return dict(_snapshot)


def restore_snapshot(snapshot: dict) -> str:
    restored = 0
    for path, content in snapshot.items():
        target = Path(path)
        try:
            if content is None:
                if target.is_file():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            restored += 1
        except Exception as exc:
            return f"ERROR restoring {path}: {exc}"
    return f"Restored {restored} file(s)."


def read_snapshot_files(snapshot: dict) -> dict:
    after = {}
    for path in snapshot:
        target = Path(path)
        try:
            after[path] = (
                target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
            )
        except Exception:
            after[path] = None
    return after


def _record_snapshot(target: Path) -> None:
    if not _snapshot_active:
        return
    key = str(target)
    if key in _snapshot:
        return
    try:
        _snapshot[key] = (
            target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
        )
    except Exception:
        _snapshot[key] = None


def read_file(path: str) -> str:
    target = _safe_path(path)
    if not target.is_file():
        return f"ERROR: file not found: {path}"
    try:
        return _truncate(target.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return f"ERROR: {exc}"


def write_file(path: str, content: str) -> str:
    target = _safe_path(path)
    previous = (
        target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
    )
    diff_lines = ""
    if previous is not None and previous != content:
        diff = list(
            difflib.unified_diff(
                previous.splitlines(), content.splitlines(), "before", "after", lineterm=""
            )
        )
        diff_lines = "\n".join(diff[:200])
        if REQUIRE_APPROVAL and not _ask_approval(f"overwrite {path}:\n{diff_lines}"):
            return f"DENIED: user did not approve overwriting {path}"
    _record_snapshot(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    if diff_lines:
        return f"Wrote {len(content)} chars to {path}\n{diff_lines}"
    return f"Wrote {len(content)} chars to {path}"


def list_dir(path: str = ".") -> str:
    target = _safe_path(path)
    if not target.is_dir():
        return f"ERROR: not a directory: {path}"
    entries = []
    for item in sorted(target.iterdir()):
        entries.append(f"{'dir ' if item.is_dir() else 'file'}  {item.name}")
    return "\n".join(entries) if entries else "(empty)"


def run_shell(command: str) -> str:
    if not ALLOW_SHELL:
        return "ERROR: shell execution is disabled (ALLOW_SHELL=false)"
    if REQUIRE_APPROVAL and _is_destructive(command):
        if not _ask_approval(f"shell command: {command}"):
            return (
                "DENIED: this command needs the user's approval. "
                "Summarize the changes and ask the user to approve before pushing or opening a PR."
            )
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(WORKSPACE),
            capture_output=True,
            text=True,
            timeout=120,
            env=_shell_env(),
        )
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out after 120s"
    except Exception as exc:
        return f"ERROR: {exc}"
    output = (result.stdout or "") + (result.stderr or "")
    return _truncate(f"exit={result.returncode}\n{output}".strip())


def _host_is_internal(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return True
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return True
    return False


def http_get(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "ERROR: only http(s) URLs are allowed"
    if not ALLOW_PRIVATE_HTTP and _host_is_internal(parsed.hostname):
        return "ERROR: blocked internal/loopback address (set ALLOW_PRIVATE_HTTP=true to allow)"
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "mybot/1.0"})
    except Exception as exc:
        return f"ERROR: {exc}"
    return _truncate(f"status={resp.status_code}\n{resp.text}")


def github_request(method: str, path: str, body=None) -> str:
    if not GITHUB_TOKEN:
        return "ERROR: GITHUB_TOKEN is not set in .env"
    method = method.upper()
    if method not in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
        return f"ERROR: unsupported method: {method}"
    if REQUIRE_APPROVAL and method != "GET" and not _ask_approval(f"GitHub {method} {path}"):
        return (
            "DENIED: this GitHub write action needs the user's approval. "
            "Explain what it would do and ask the user to approve."
        )
    if path.startswith("http"):
        if not path.startswith(GITHUB_API):
            return "ERROR: github_request may only call https://api.github.com"
        url = path
    else:
        url = GITHUB_API + (path if path.startswith("/") else "/" + path)
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "mybot/1.0",
    }
    try:
        resp = requests.request(method, url, headers=headers, json=body, timeout=30)
    except Exception as exc:
        return f"ERROR: {exc}"
    return _truncate(f"status={resp.status_code}\n{resp.text}")


def launch_app(target: str) -> str:
    try:
        os.startfile(target)  # noqa: S606 - Windows shell open
    except Exception as exc:
        return f"ERROR: {exc}"
    return f"Launched: {target}"


def _pyautogui():
    try:
        import pyautogui
    except ImportError:
        return None
    return pyautogui


def gui_click(x: int, y: int) -> str:
    pg = _pyautogui()
    if pg is None:
        return "ERROR: gui tools need pyautogui (pip install pyautogui)"
    pg.click(int(x), int(y))
    return f"Clicked at {x},{y}"


def gui_type(text: str) -> str:
    pg = _pyautogui()
    if pg is None:
        return "ERROR: gui tools need pyautogui (pip install pyautogui)"
    pg.write(text, interval=0.02)
    return f"Typed {len(text)} chars"


def gui_hotkey(keys: list) -> str:
    pg = _pyautogui()
    if pg is None:
        return "ERROR: gui tools need pyautogui (pip install pyautogui)"
    pg.hotkey(*keys)
    return f"Pressed {'+'.join(keys)}"


def gui_screenshot(path: str = "screenshot.png") -> str:
    pg = _pyautogui()
    if pg is None:
        return "ERROR: gui tools need pyautogui (pip install pyautogui)"
    target = _safe_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    pg.screenshot(str(target))
    return f"Saved screenshot to {path}"


def schedule_task(name: str, command: str, schedule: str = "DAILY", time: str = "09:00") -> str:
    schedule = schedule.upper()
    allowed = {"MINUTE", "HOURLY", "DAILY", "WEEKLY", "ONCE", "ONLOGON", "ONSTART"}
    if schedule not in allowed:
        return f"ERROR: schedule must be one of {sorted(allowed)}"
    if REQUIRE_APPROVAL and not _ask_approval(f"create scheduled task: {name} -> {command}"):
        return "DENIED: creating a scheduled task needs the user's approval."
    cmd = ["schtasks", "/Create", "/TN", name, "/TR", command, "/SC", schedule, "/F"]
    if schedule in {"DAILY", "WEEKLY", "ONCE", "MINUTE", "HOURLY"} and time:
        cmd += ["/ST", time]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as exc:
        return f"ERROR: {exc}"
    output = (result.stdout or "") + (result.stderr or "")
    return _truncate(f"exit={result.returncode}\n{output}".strip())


def list_tasks(filter_text: str = "") -> str:
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/FO", "TABLE"], capture_output=True, text=True, timeout=60
        )
    except Exception as exc:
        return f"ERROR: {exc}"
    output = (result.stdout or "") + (result.stderr or "")
    if filter_text:
        lines = [line for line in output.splitlines() if filter_text.lower() in line.lower()]
        output = "\n".join(lines)
    return _truncate(output)


def delete_task(name: str) -> str:
    if REQUIRE_APPROVAL and not _ask_approval(f"delete scheduled task: {name}"):
        return "DENIED: deleting a scheduled task needs the user's approval."
    try:
        result = subprocess.run(
            ["schtasks", "/Delete", "/TN", name, "/F"], capture_output=True, text=True, timeout=60
        )
    except Exception as exc:
        return f"ERROR: {exc}"
    output = (result.stdout or "") + (result.stderr or "")
    return _truncate(f"exit={result.returncode}\n{output}".strip())


_todos: list = []


def get_todos() -> list:
    return list(_todos)


def _render_todos() -> str:
    if not _todos:
        return "(no todos)"
    marks = {"completed": "[x]", "in_progress": "[~]", "pending": "[ ]"}
    return "\n".join(f"{marks.get(item['status'], '[ ]')} {item['content']}" for item in _todos)


def todo_write(todos: list = None) -> str:
    global _todos
    if todos is None:
        return _render_todos()
    normalized = []
    for item in todos:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        status = item.get("status", "pending")
        if status not in {"pending", "in_progress", "completed"}:
            status = "pending"
        if content:
            normalized.append({"content": content, "status": status})
    _todos = normalized
    return _render_todos()


def remember(text: str) -> str:
    from memory import add_note

    return add_note(text)


def add_trigger(kind: str, target: str = "", command: str = "", seconds: int = 0) -> str:
    from triggers import add_trigger as _add

    kind = (kind or "").strip().lower()
    if kind not in {"watch", "interval"}:
        return "ERROR: kind must be 'watch' or 'interval'"
    if not command:
        return "ERROR: command is required"
    if kind == "watch" and not target:
        return "ERROR: watch requires a target path"
    if kind == "interval" and int(seconds or 0) <= 0:
        return "ERROR: interval requires seconds > 0"
    trigger = _add(kind, target, command, seconds)
    where = target if kind == "watch" else f"every {seconds}s"
    return f"Added trigger {trigger['id']}: {kind} ({where}) -> {command}"


def list_triggers() -> str:
    from triggers import load_triggers

    triggers = load_triggers()
    if not triggers:
        return "(no triggers)"
    lines = []
    for t in triggers:
        where = t.get("target") if t.get("kind") == "watch" else f"{t.get('seconds')}s"
        lines.append(f"{t['id']} [{t['kind']}] {where} -> {t.get('command', '')}")
    return "\n".join(lines)


def remove_trigger(trigger_id: str) -> str:
    from triggers import remove_trigger as _remove

    return f"Removed {_remove(trigger_id)} trigger(s)."


def recall(query: str = "") -> str:
    from memory import format_notes, search_notes

    notes = search_notes(query)
    if not notes:
        return "No matching memories." if query else format_notes()
    return "\n".join(f"- {note.get('text', '')}" for note in notes[-50:])


TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file from the workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Relative file path"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"},
                    "content": {"type": "string", "description": "File contents"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and folders inside a workspace directory.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Relative directory path"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run a shell command in the workspace and return its output.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "Command to run"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "http_get",
            "description": "Fetch the contents of a URL via HTTP GET.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "URL to fetch"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_request",
            "description": (
                "Call the GitHub REST API with the configured token. Use for reading issues "
                "and creating PRs or comments. Example path: /repos/OWNER/REPO/issues/5"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "enum": ["GET", "POST", "PATCH", "PUT", "DELETE"],
                        "description": "HTTP method",
                    },
                    "path": {
                        "type": "string",
                        "description": "API path like /repos/OWNER/REPO/issues/5 or a full URL",
                    },
                    "body": {
                        "type": "object",
                        "description": "Optional JSON body for POST/PATCH/PUT",
                    },
                },
                "required": ["method", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "launch_app",
            "description": "Open a program, file, folder, or URL with its default application.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Path, executable, or URL to open"}
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gui_click",
            "description": "Move the mouse and click at screen coordinates.",
            "parameters": {
                "type": "object",
                "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gui_type",
            "description": "Type text at the current focus using the keyboard.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gui_hotkey",
            "description": "Press a key combination, e.g. ['ctrl', 's'].",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["keys"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gui_screenshot",
            "description": "Capture the screen and save it into the workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Output path"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_task",
            "description": "Create a Windows scheduled task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "command": {"type": "string", "description": "Program/command to run"},
                    "schedule": {
                        "type": "string",
                        "enum": ["MINUTE", "HOURLY", "DAILY", "WEEKLY", "ONCE", "ONLOGON", "ONSTART"],
                    },
                    "time": {"type": "string", "description": "Start time HH:MM, e.g. 09:00"},
                },
                "required": ["name", "command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List Windows scheduled tasks, optionally filtered by text.",
            "parameters": {
                "type": "object",
                "properties": {"filter_text": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": "Delete a Windows scheduled task by name.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": (
                "Create or update the task plan. Pass the complete list every call, each item "
                "with content and status (pending, in_progress, completed)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                },
                            },
                            "required": ["content", "status"],
                        },
                    }
                },
                "required": ["todos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": (
                "Save a durable fact about the user or project to long-term memory. "
                "The most recent memories are automatically included in your context."
            ),
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "Look up saved memories, optionally filtered by a query.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_trigger",
            "description": (
                "Create a background trigger: kind 'interval' runs the command every "
                "`seconds`; kind 'watch' runs it whenever `target` (a file/folder) changes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["watch", "interval"]},
                    "target": {"type": "string", "description": "Path to watch"},
                    "command": {"type": "string", "description": "Shell command to run"},
                    "seconds": {"type": "integer", "description": "Interval seconds"},
                },
                "required": ["kind", "command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_triggers",
            "description": "List the configured background triggers.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_trigger",
            "description": "Remove a background trigger by id.",
            "parameters": {
                "type": "object",
                "properties": {"trigger_id": {"type": "string"}},
                "required": ["trigger_id"],
            },
        },
    },
]

_DISPATCH = {
    "read_file": read_file,
    "write_file": write_file,
    "list_dir": list_dir,
    "run_shell": run_shell,
    "http_get": http_get,
    "github_request": github_request,
    "launch_app": launch_app,
    "gui_click": gui_click,
    "gui_type": gui_type,
    "gui_hotkey": gui_hotkey,
    "gui_screenshot": gui_screenshot,
    "schedule_task": schedule_task,
    "list_tasks": list_tasks,
    "delete_task": delete_task,
    "todo_write": todo_write,
    "remember": remember,
    "recall": recall,
    "add_trigger": add_trigger,
    "list_triggers": list_triggers,
    "remove_trigger": remove_trigger,
}


def execute_tool(name: str, arguments: str) -> str:
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"ERROR: unknown tool: {name}"
    try:
        args = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError as exc:
        return f"ERROR: invalid arguments for {name}: {exc}"
    try:
        return fn(**args)
    except TypeError as exc:
        return f"ERROR: bad arguments for {name}: {exc}"
    except Exception as exc:
        return f"ERROR: {name} failed: {exc}"
