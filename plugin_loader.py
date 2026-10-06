import importlib.util
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PLUGIN_DIRS = [BASE_DIR / "plugins"]

_tool_specs = []
_tools = {}
_commands = {}
_hooks = {}
_log = []
_loaded = []


def _add_tool(name, func, description, parameters):
    _tools[name] = func
    _tool_specs.append(
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description or name,
                "parameters": parameters
                or {"type": "object", "properties": {}, "required": []},
            },
        }
    )


def _add_command(name, func, description=""):
    key = name if name.startswith("/") else "/" + name
    _commands[key] = {"func": func, "description": description}


def _add_hook(event, handler):
    _hooks.setdefault(event, []).append(handler)


class PluginAPI:
    """Passed to each plugin's `register(api)` function."""

    def register_tool(self, name, func, description="", parameters=None):
        _add_tool(name, func, description, parameters)

    def register_command(self, name, func, description=""):
        _add_command(name, func, description)

    def on(self, event, handler):
        _add_hook(event, handler)

    def log(self, message):
        _log.append(str(message))


def tool_specs() -> list:
    return list(_tool_specs)


def get_tool(name: str):
    return _tools.get(name)


def commands() -> dict:
    return dict(_commands)


def run_command(name: str, text: str):
    entry = _commands.get(name if name.startswith("/") else "/" + name)
    if entry is None:
        return None
    try:
        result = entry["func"](text)
        return str(result) if result is not None else ""
    except Exception as exc:
        return f"plugin command error: {exc}"


def emit(event: str, **kwargs) -> None:
    for handler in _hooks.get(event, []):
        try:
            handler(**kwargs)
        except Exception as exc:
            _log.append(f"plugin hook '{event}' error: {exc}")


def loaded() -> list:
    return list(_loaded)


def load_errors() -> list:
    return list(_log)


def reload() -> list:
    _tool_specs.clear()
    _tools.clear()
    _commands.clear()
    _hooks.clear()
    _log.clear()
    _loaded.clear()
    return load_plugins()


def load_plugins() -> list:
    for directory in PLUGIN_DIRS:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"mybot_plugin_{path.stem}", path
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                register = getattr(module, "register", None)
                if callable(register):
                    register(PluginAPI())
                _loaded.append(path.stem)
            except Exception as exc:
                _log.append(f"plugin {path.name} failed: {exc}")
    return list(_loaded)
