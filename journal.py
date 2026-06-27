"""
Macro views journal — CRUD for views_journal.json.
All state lives in a single JSON file in the project root.
"""

import json
import uuid
from pathlib import Path

_JOURNAL_PATH = Path(__file__).parent / "views_journal.json"


def _load() -> list[dict]:
    if not _JOURNAL_PATH.exists():
        return []
    try:
        return json.loads(_JOURNAL_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(entries: list[dict]) -> None:
    _JOURNAL_PATH.write_text(
        json.dumps(entries, indent=2, default=str), encoding="utf-8"
    )


def load_entries() -> list[dict]:
    """Return all journal entries, newest first."""
    return sorted(_load(), key=lambda e: e.get("date", ""), reverse=True)


def save_entry(entry: dict) -> str:
    """Append a new entry (auto-assigns UUID). Returns the new entry id."""
    entries = _load()
    entry["id"] = str(uuid.uuid4())
    entries.append(entry)
    _save(entries)
    return entry["id"]


def delete_entry(entry_id: str) -> None:
    entries = [e for e in _load() if e.get("id") != entry_id]
    _save(entries)
