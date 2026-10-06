import argparse
import ast
import re
import shutil
import sys
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PLUGINS_DIR = BASE_DIR / "plugins"
DISABLED_DIR = PLUGINS_DIR / ".disabled"


def _ensure_dirs() -> None:
    PLUGINS_DIR.mkdir(exist_ok=True)
    DISABLED_DIR.mkdir(exist_ok=True)


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
    lines = [f"{action} {path.name}"]
    if tools:
        lines.append("  tools: " + ", ".join(tools))
    if commands:
        lines.append("  commands: " + ", ".join("/" + c.lstrip("/") for c in commands))
    if hooks:
        lines.append("  hooks: " + ", ".join(hooks))
    if not (tools or commands or hooks):
        lines.append("  (registers nothing detectable)")
    lines.append("Restart or run /plugins to activate. Only install plugins you trust.")
    return "\n".join(lines)


def _filename_from_url(url: str) -> str:
    name = url.split("?", 1)[0].rstrip("/").split("/")[-1] or "plugin"
    if not name.endswith(".py"):
        name += ".py"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def install(source: str) -> str:
    _ensure_dirs()
    if source.startswith(("http://", "https://")):
        name = _filename_from_url(source)
        dest = PLUGINS_DIR / name
        try:
            with urllib.request.urlopen(source, timeout=30) as resp:
                data = resp.read()
        except Exception as exc:
            return f"ERROR: download failed: {exc}"
        dest.write_bytes(data)
    else:
        src = Path(source).expanduser()
        if not src.is_file():
            return f"ERROR: file not found: {source}"
        dest = PLUGINS_DIR / src.name
        shutil.copyfile(src, dest)
    if not _is_plugin(dest):
        dest.unlink(missing_ok=True)
        return "ERROR: not a mybot plugin (no top-level register(api) function)"
    return _summarize(dest, "Installed")


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
    p_install = sub.add_parser("install", help="install a plugin from a file or URL")
    p_install.add_argument("source")
    p_enable = sub.add_parser("enable", help="enable a disabled plugin")
    p_enable.add_argument("name")
    p_disable = sub.add_parser("disable", help="disable a plugin without deleting it")
    p_disable.add_argument("name")
    sub.add_parser("list", help="list plugins")

    args = parser.parse_args()
    if args.cmd == "install":
        print(install(args.source))
    elif args.cmd == "enable":
        print(enable(args.name))
    elif args.cmd == "disable":
        print(disable(args.name))
    elif args.cmd == "list":
        enabled, disabled = installed()
        print("enabled:", ", ".join(enabled) or "(none)")
        print("disabled:", ", ".join(disabled) or "(none)")


if __name__ == "__main__":
    main()
