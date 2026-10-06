import json
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MEMORY_PATH = BASE_DIR / ".mybot_memory.json"
SESSIONS_PATH = BASE_DIR / ".mybot_sessions.json"
HISTORY_PATH = BASE_DIR / ".mybot_history.json"


def load_notes() -> list:
    if MEMORY_PATH.is_file():
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_notes(notes: list) -> None:
    MEMORY_PATH.write_text(json.dumps(notes[-500:], indent=2), encoding="utf-8")


def add_note(text: str) -> str:
    text = text.strip()
    if not text:
        return "Nothing to remember."
    notes = load_notes()
    notes.append({"text": text, "time": time.time()})
    save_notes(notes)
    return f"Remembered ({len(notes)} total)."


def search_notes(query: str = "") -> list:
    notes = load_notes()
    if not query:
        return notes
    needle = query.lower()
    return [note for note in notes if needle in note.get("text", "").lower()]


def format_notes(limit: int = 12) -> str:
    notes = load_notes()[-limit:]
    if not notes:
        return "(nothing remembered yet)"
    return "\n".join(f"- {note.get('text', '')}" for note in notes)


def load_history() -> list:
    if HISTORY_PATH.is_file():
        try:
            data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            return [str(item) for item in data] if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_history(history: list) -> None:
    HISTORY_PATH.write_text(json.dumps(history[-500:]), encoding="utf-8")


def save_sessions(sessions: list) -> None:
    SESSIONS_PATH.write_text(json.dumps(sessions, indent=2), encoding="utf-8")


def load_sessions() -> list:
    if SESSIONS_PATH.is_file():
        try:
            data = json.loads(SESSIONS_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []
    return []
