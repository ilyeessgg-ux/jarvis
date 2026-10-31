"""Thread-safe event bus used to stream assistant activity to the HUD."""

from __future__ import annotations

import queue
import threading
import time
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self._last_state: dict[str, Any] = {"state": "idle"}

    def subscribe(self) -> queue.Queue:
        subscriber: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def publish(self, event_type: str, **payload: Any) -> None:
        event = {"type": event_type, "ts": time.time(), **payload}
        if event_type == "state":
            self._last_state = event
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(event)
                except (queue.Empty, queue.Full):
                    pass

    @property
    def last_state(self) -> dict[str, Any]:
        return self._last_state
