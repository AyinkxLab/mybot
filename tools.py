import json
import subprocess
from pathlib import Path

import requests

from config import ALLOW_SHELL, WORKSPACE

MAX_OUTPUT = 8000


def _safe_path(relative: str) -> Path:
    target = (WORKSPACE / relative).resolve()
    if WORKSPACE != target and WORKSPACE not in target.parents:
        raise ValueError(f"Path escapes workspace: {relative}")
    return target


def _truncate(text: str) -> str:
    if len(text) > MAX_OUTPUT:
        return text[:MAX_OUTPUT] + f"\n...[truncated {len(text) - MAX_OUTPUT} chars]"
    return text


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
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
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
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(WORKSPACE),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out after 120s"
    except Exception as exc:
        return f"ERROR: {exc}"
    output = (result.stdout or "") + (result.stderr or "")
    return _truncate(f"exit={result.returncode}\n{output}".strip())


def http_get(url: str) -> str:
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "mybot/1.0"})
    except Exception as exc:
        return f"ERROR: {exc}"
    return _truncate(f"status={resp.status_code}\n{resp.text}")


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
]

_DISPATCH = {
    "read_file": read_file,
    "write_file": write_file,
    "list_dir": list_dir,
    "run_shell": run_shell,
    "http_get": http_get,
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
