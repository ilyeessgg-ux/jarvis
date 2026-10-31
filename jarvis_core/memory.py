"""SQLite-backed conversation, memory, notes, reminders, and settings."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .config import BOOLEAN_SETTINGS, DATA_DIR, DEFAULT_SETTINGS, FLOAT_SETTINGS


class Memory:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (DATA_DIR / "jarvis.db")
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._create_schema()
            self._seed_settings()

    def _create_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS facts (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                due_at REAL NOT NULL,
                created_at REAL NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                notified INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def _seed_settings(self) -> None:
        for key, value in DEFAULT_SETTINGS.items():
            self._conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, self._serialise_setting(value)),
            )
        self._conn.commit()

    # ------------------------------------------------------------------ messages
    def add_message(self, role: str, content: str) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO messages(role, content, created_at) VALUES (?, ?, ?)",
                (role, content, time.time()),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def recent_messages(self, limit: int = 24) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content, created_at FROM messages ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"role": row["role"], "content": row["content"], "ts": row["created_at"]}
            for row in reversed(rows)
        ]

    def clear_messages(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM messages")
            self._conn.commit()

    # ---------------------------------------------------------------------- facts
    def set_fact(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO facts(key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key.strip().lower(), value.strip(), time.time()),
            )
            self._conn.commit()

    def facts(self, query: str | None = None) -> list[dict[str, str]]:
        with self._lock:
            if query:
                rows = self._conn.execute(
                    "SELECT key, value FROM facts WHERE key LIKE ? OR value LIKE ? ORDER BY key",
                    (f"%{query}%", f"%{query}%"),
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT key, value FROM facts ORDER BY key").fetchall()
        return [{"key": row["key"], "value": row["value"]} for row in rows]

    def forget_fact(self, key: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM facts WHERE key = ?", (key.strip().lower(),))
            self._conn.commit()
            return cursor.rowcount > 0

    # ---------------------------------------------------------------------- notes
    def add_note(self, title: str, content: str) -> int:
        now = time.time()
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO notes(title, content, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (title.strip(), content.strip(), now, now),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def search_notes(self, query: str = "", limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            if query:
                rows = self._conn.execute(
                    "SELECT id, title, content, created_at FROM notes "
                    "WHERE title LIKE ? OR content LIKE ? ORDER BY updated_at DESC LIMIT ?",
                    (f"%{query}%", f"%{query}%", limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id, title, content, created_at FROM notes ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def delete_note(self, note_id: int) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            self._conn.commit()
            return cursor.rowcount > 0

    # ------------------------------------------------------------------ reminders
    def add_reminder(self, text: str, due_at: float) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO reminders(text, due_at, created_at) VALUES (?, ?, ?)",
                (text.strip(), due_at, time.time()),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def reminders(self, include_done: bool = False) -> list[dict[str, Any]]:
        query = "SELECT id, text, due_at, done FROM reminders"
        params: tuple = ()
        if not include_done:
            query += " WHERE done = 0"
        query += " ORDER BY due_at"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def due_reminders(self, now: float | None = None) -> list[dict[str, Any]]:
        now = now or time.time()
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, text, due_at FROM reminders "
                "WHERE done = 0 AND notified = 0 AND due_at <= ? ORDER BY due_at",
                (now,),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_reminder(self, reminder_id: int, done: bool = True) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE reminders SET notified = 1, done = ? WHERE id = ?",
                (1 if done else 0, reminder_id),
            )
            self._conn.commit()

    def cancel_reminder(self, reminder_id: int | None = None, text: str | None = None) -> int:
        with self._lock:
            if reminder_id is not None:
                cursor = self._conn.execute(
                    "UPDATE reminders SET done = 1, notified = 1 WHERE id = ? AND done = 0",
                    (reminder_id,),
                )
            elif text:
                cursor = self._conn.execute(
                    "UPDATE reminders SET done = 1, notified = 1 WHERE done = 0 AND text LIKE ?",
                    (f"%{text}%",),
                )
            else:
                return 0
            self._conn.commit()
            return cursor.rowcount

    # ------------------------------------------------------------------- settings
    @staticmethod
    def _serialise_setting(value: Any) -> str:
        if isinstance(value, bool):
            return "1" if value else "0"
        return str(value)

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return DEFAULT_SETTINGS.get(key, default)
        raw = row["value"]
        if key in BOOLEAN_SETTINGS:
            return raw in {"1", "true", "True", "yes", "on"}
        if key in FLOAT_SETTINGS:
            try:
                return float(raw)
            except ValueError:
                return float(DEFAULT_SETTINGS.get(key, 0.5))
        return raw

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, self._serialise_setting(value)),
            )
            self._conn.commit()

    def settings(self) -> dict[str, Any]:
        return {key: self.get_setting(key) for key in DEFAULT_SETTINGS}

    # --------------------------------------------------------------------- misc
    def stats(self) -> dict[str, int]:
        with self._lock:
            messages = self._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            facts = self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            notes = self._conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            reminders = self._conn.execute(
                "SELECT COUNT(*) FROM reminders WHERE done = 0"
            ).fetchone()[0]
        return {
            "messages": int(messages),
            "facts": int(facts),
            "notes": int(notes),
            "reminders": int(reminders),
        }

    def export_json(self) -> str:
        with self._lock:
            data = {
                "messages": [dict(row) for row in self._conn.execute("SELECT * FROM messages")],
                "facts": [dict(row) for row in self._conn.execute("SELECT * FROM facts")],
                "notes": [dict(row) for row in self._conn.execute("SELECT * FROM notes")],
                "reminders": [dict(row) for row in self._conn.execute("SELECT * FROM reminders")],
                "settings": self.settings(),
            }
        return json.dumps(data, indent=2)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
