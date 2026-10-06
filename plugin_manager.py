import argparse
import ast
import json
import os
import re
import shutil
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PLUGINS_DIR = BASE_DIR / "plugins"
DISABLED_DIR = PLUGINS_DIR / ".disabled"
AVAILABLE_DIR = PLUGINS_DIR / "available"
REGISTRY_PATH = BASE_DIR / "plugin_registry.json"


def _ensure_dirs() -> None:
    PLUGINS_DIR.mkdir(exist_ok=True)
    DISABLED_DIR.mkdir(exist_ok=True)
    AVAILABLE_DIR.mkdir(exist_ok=True)


def _is_plugin(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return False
    return any(
        isinstance(node, ast.FunctionDef) and node.name == "register" for node in tree.body
    )


def _describe(path: Path):
    tools, commands, hooks = [], [], []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return tools, commands, hooks
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            arg = node.args[0] if node.args else None
            name = arg.value if isinstance(arg, ast.Constant) else None
            if attr == "register_tool" and name:
                tools.append(name)
            elif attr == "register_command" and name:
                commands.append(name)
            elif attr == "on" and name:
                hooks.append(name)
    return tools, commands, hooks


def _summarize(path: Path, action: str) -> str:
    tools, commands, hooks = _describe(path)
    lines = [action]
    if tools:
        lines.append("  tools: " + ", ".join(tools))
    if commands:
        lines.append("  commands: " + ", ".join("/" + c.lstrip("/") for c in commands))
    if hooks:
        lines.append("  hooks: " + ", ".join(hooks))
    if not (tools or commands or hooks):
        lines.append("  (registers nothing detectable)")
    lines.append("Activated now. Only install plugins you trust.")
    return "\n".join(lines)


def registry() -> list:
    entries = []
    if REGISTRY_PATH.is_file():
        try:
            data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            entries += data.get("plugins", []) if isinstance(data, dict) else []
        except (json.JSONDecodeError, OSError):
            pass
    url = os.environ.get("MYBOT_PLUGIN_REGISTRY_URL")
    if url:
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            entries += data.get("plugins", []) if isinstance(data, dict) else []
        except Exception:
            pass
    return entries


def find(name: str):
    for entry in registry():
        if entry.get("name") == name:
            return entry
    return None


def search(query: str = "") -> list:
    needle = (query or "").lower()
    results = []
    for entry in registry():
        haystack = " ".join(
            [str(entry.get("name", "")), str(entry.get("description", ""))]
            + list(entry.get("tags", []))
        ).lower()
        if not needle or needle in haystack:
            results.append(entry)
    return results


def _filename_from_url(url: str) -> str:
    name = url.split("?", 1)[0].rstrip("/").split("/")[-1] or "plugin"
    if not name.endswith(".py"):
        name += ".py"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def _install_bytes(data: bytes, name: str) -> str:
    dest = PLUGINS_DIR / f"{name}.py"
    dest.write_bytes(data)
    if not _is_plugin(dest):
        dest.unlink(missing_ok=True)
        return "ERROR: not a mybot plugin (no top-level register(api) function)"
    return _summarize(dest, f"Installed {name}")


def install(source: str) -> str:
    _ensure_dirs()
    is_url = source.startswith(("http://", "https://"))
    entry = find(source) or (find(Path(source).stem) if not is_url else None)
    if entry:
        filename = entry.get("file")
        if filename:
            bundled = AVAILABLE_DIR / filename
            if not bundled.is_file():
                return f"ERROR: bundled file missing: {filename}"
            return _install_bytes(bundled.read_bytes(), entry["name"])
        url = entry.get("url")
        if url:
            try:
                data = urllib.request.urlopen(url, timeout=30).read()
            except Exception as exc:
                return f"ERROR: download failed: {exc}"
            return _install_bytes(data, entry["name"])
    if is_url:
        name = _filename_from_url(source)[:-3]
        try:
            data = urllib.request.urlopen(source, timeout=30).read()
        except Exception as exc:
            return f"ERROR: download failed: {exc}"
        return _install_bytes(data, name)
    path = Path(source).expanduser()
    if not path.is_file():
        return f"ERROR: file not found: {source} (and no registry plugin named '{source}')"
    return _install_bytes(path.read_bytes(), path.stem)


def installed():
    _ensure_dirs()
    enabled = sorted(p.stem for p in PLUGINS_DIR.glob("*.py") if not p.name.startswith("_"))
    disabled = sorted(p.stem for p in DISABLED_DIR.glob("*.py"))
    return enabled, disabled


def disable(name: str) -> str:
    _ensure_dirs()
    src = PLUGINS_DIR / f"{name}.py"
    if not src.is_file():
        return f"ERROR: no enabled plugin named '{name}'"
    src.replace(DISABLED_DIR / src.name)
    return f"Disabled {name}"


def enable(name: str) -> str:
    _ensure_dirs()
    src = DISABLED_DIR / f"{name}.py"
    if not src.is_file():
        return f"ERROR: no disabled plugin named '{name}'"
    src.replace(PLUGINS_DIR / src.name)
    return f"Enabled {name}"


def main() -> None:
    parser = argparse.ArgumentParser(prog="mybot-plugin", description="Manage mybot plugins")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_install = sub.add_parser("install", help="install by name, local path, or URL")
    p_install.add_argument("source")
    sub.add_parser("list", help="list installed plugins")
    sub.add_parser("available", help="list plugins you can install")
    p_search = sub.add_parser("search", help="search the registry")
    p_search.add_argument("query", nargs="?", default="")
    p_enable = sub.add_parser("enable", help="enable a disabled plugin")
    p_enable.add_argument("name")
    p_disable = sub.add_parser("disable", help="disable a plugin without deleting it")
    p_disable.add_argument("name")

    args = parser.parse_args()
    if args.cmd == "install":
        print(install(args.source))
    elif args.cmd == "list":
        enabled, disabled = installed()
        print("enabled:", ", ".join(enabled) or "(none)")
        print("disabled:", ", ".join(disabled) or "(none)")
    elif args.cmd == "available":
        for entry in registry():
            print(f"{entry.get('name'):16} {entry.get('description', '')}")
    elif args.cmd == "search":
        for entry in search(args.query):
            print(f"{entry.get('name'):16} {entry.get('description', '')}")
    elif args.cmd == "enable":
        print(enable(args.name))
    elif args.cmd == "disable":
        print(disable(args.name))


if __name__ == "__main__":
    main()
