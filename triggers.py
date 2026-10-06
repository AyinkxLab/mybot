import json
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TRIGGERS_PATH = BASE_DIR / ".mybot_triggers.json"

_counter = {"n": 0}


def load_triggers() -> list:
    if TRIGGERS_PATH.is_file():
        try:
            data = json.loads(TRIGGERS_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_triggers(triggers: list) -> None:
    TRIGGERS_PATH.write_text(json.dumps(triggers, indent=2), encoding="utf-8")


def add_trigger(kind: str, target: str = "", command: str = "", seconds: int = 0) -> dict:
    triggers = load_triggers()
    _counter["n"] += 1
    trigger = {
        "id": f"t{int(time.time())}{_counter['n']}",
        "kind": kind,
        "target": target,
        "command": command,
        "seconds": int(seconds or 0),
        "enabled": True,
        "last": 0.0,
        "stamp": None,
        "based": False,
    }
    triggers.append(trigger)
    save_triggers(triggers)
    return trigger


def remove_trigger(trigger_id: str) -> int:
    triggers = load_triggers()
    kept = [t for t in triggers if t.get("id") != trigger_id]
    save_triggers(kept)
    return len(triggers) - len(kept)


def _stamp(path: str):
    try:
        p = Path(path)
        return p.stat().st_mtime if p.exists() else None
    except Exception:
        return None


def evaluate(now: float = None) -> list:
    now = now if now is not None else time.time()
    triggers = load_triggers()
    fired = []
    changed = False
    for t in triggers:
        if not t.get("enabled", True):
            continue
        if t.get("kind") == "interval":
            seconds = int(t.get("seconds") or 0)
            if seconds > 0 and now - float(t.get("last") or 0) >= seconds:
                t["last"] = now
                fired.append(t)
                changed = True
        elif t.get("kind") == "watch":
            stamp = _stamp(t.get("target", ""))
            if not t.get("based"):
                t["stamp"] = stamp
                t["based"] = True
                changed = True
            elif stamp != t.get("stamp"):
                t["stamp"] = stamp
                fired.append(t)
                changed = True
    if changed:
        save_triggers(triggers)
    return fired
