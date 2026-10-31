"""Background reminder scheduler."""

from __future__ import annotations

import threading
import time
from typing import Callable

from .memory import Memory


class ReminderScheduler:
    def __init__(self, memory: Memory, on_due: Callable[[dict], None]) -> None:
        self.memory = memory
        self.on_due = on_due
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="jarvis-reminders", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                for reminder in self.memory.due_reminders():
                    self.memory.mark_reminder(reminder["id"], done=True)
                    self.on_due(reminder)
            except Exception:
                pass
            self._stop.wait(5.0)
