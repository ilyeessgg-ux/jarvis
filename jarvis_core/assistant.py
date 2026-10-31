"""J.A.R.V.I.S. orchestration: conversation, tools, voice, memory, state."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from datetime import datetime
from typing import Any

import numpy as np

from .audio import AudioEngine
from .config import (
    CONFIG_FILE,
    DATA_DIR,
    DEFAULT_SETTINGS,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    PERSONA,
    QUICK_PROMPTS,
    VOICES,
)
from .events import EventBus
from .llm import LLMClient, OpenRouterError
from .memory import Memory
from .scheduler import ReminderScheduler
from .stt import STTEngine
from .tools import Toolbox
from .tts import TTSEngine

log = logging.getLogger("jarvis.assistant")

MAX_TOOL_ROUNDS = 6


class Assistant:
    def __init__(self, memory: Memory | None = None, greeting: bool = True) -> None:
        self.memory = memory or Memory()
        self._greeting_enabled = greeting
        self.settings: dict[str, Any] = self.memory.settings()
        self.bus = EventBus()
        self.started_at = time.time()
        self.llm = LLMClient(OPENROUTER_API_KEY, OPENROUTER_BASE_URL, self.settings["model"])
        self.tts = TTSEngine()
        self.stt = STTEngine()
        self.toolbox = Toolbox(self.memory, lambda: self.settings)
        self.scheduler = ReminderScheduler(self.memory, self._on_reminder_due)
        self.audio = AudioEngine(
            settings_getter=lambda: self.settings,
            on_wake=self._on_wake,
            on_command=self._on_command_audio,
            on_level=self._on_level,
            on_error=self._on_audio_error,
            on_state=self._on_audio_state,
        )
        self._state = "boot"
        self._state_detail = ""
        self._state_lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._cancel = threading.Event()
        self._stop = threading.Event()
        self._task_active = threading.Event()
        self._speaking = threading.Event()

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._worker = threading.Thread(target=self._worker_loop, name="jarvis-brain", daemon=True)
        self._worker.start()
        self.audio.start()
        self.scheduler.start()
        threading.Thread(target=self._preload_stt, name="jarvis-stt-preload", daemon=True).start()
        self.set_state("idle", "All systems online")
        threading.Thread(target=self._startup_greeting, name="jarvis-greeting", daemon=True).start()
        log.info("Assistant started")

    def _preload_stt(self) -> None:
        # Give the wake-word model and microphone the CPU first, otherwise the
        # Whisper preload can delay voice arming by tens of seconds.
        for _ in range(75):
            if self.audio.available or self.audio.last_error:
                break
            time.sleep(0.2)
        time.sleep(1.0)
        self.stt.preload()

    def shutdown(self) -> None:
        self._stop.set()
        self.audio.stop()
        self.scheduler.stop()
        self.tts.stop()
        self._queue.put(None)
        if self._worker:
            self._worker.join(timeout=3.0)
        self.memory.close()
        log.info("Assistant stopped")

    def _startup_greeting(self) -> None:
        if not self._greeting_enabled:
            return
        time.sleep(2.2)
        if self._task_active.is_set() or self._speaking.is_set() or not self.settings.get("speak_replies"):
            return
        hour = datetime.now().hour
        if hour < 12:
            greeting = "Good morning"
        elif hour < 18:
            greeting = "Good afternoon"
        else:
            greeting = "Good evening"
        name = self.settings.get("user_name", "sir")
        text = f"{greeting}, {name}. All systems are online and standing by."
        self.emit("assistant_done", id=str(uuid.uuid4()), text=text, source="startup", model=None)
        self.memory.add_message("assistant", text)
        self._speak(text)

    # -------------------------------------------------------------------- events
    def emit(self, event_type: str, **payload: Any) -> None:
        self.bus.publish(event_type, **payload)

    def set_state(self, state: str, detail: str = "") -> None:
        with self._state_lock:
            changed = state != self._state or detail != getattr(self, "_state_detail", "")
            self._state = state
            self._state_detail = detail
        if changed:
            self.emit("state", state=state, detail=detail)

    @property
    def state(self) -> str:
        return self._state

    # ------------------------------------------------------------------- input
    def submit_text(self, text: str, source: str = "ui") -> bool:
        text = (text or "").strip()
        if not text:
            return False
        self._queue.put(("text", {"text": text, "source": source}))
        self.emit("queued", kind="text")
        return True

    def _on_command_audio(self, audio: np.ndarray) -> None:
        self._queue.put(("audio", {"audio": audio}))

    def _on_wake(self) -> None:
        self.emit("wake", phrase="Hey Jarvis")
        self.set_state("listening", "Wake word detected")

    def _on_level(self, level: float) -> None:
        self.emit("level", level=round(level, 4))

    def _on_audio_state(self, state: str) -> None:
        if state == "armed":
            self.emit("audio", available=True, message="Microphone armed")

    def _on_audio_error(self, message: str) -> None:
        self.emit("audio", available=self.audio.available, message=message)
        self.emit("toast", level="warn", text=message)
        if self.state in {"listening", "recording", "transcribing"}:
            self.set_state("idle")

    def _on_reminder_due(self, reminder: dict[str, Any]) -> None:
        self._queue.put(("reminder", reminder))

    # ------------------------------------------------------------------- worker
    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                task = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if task is None:
                break
            kind, payload = task
            self._task_active.set()
            self.audio.pause()
            try:
                if kind == "text":
                    self._process_text(payload["text"], payload.get("source", "ui"))
                elif kind == "audio":
                    self._process_audio(payload["audio"])
                elif kind == "reminder":
                    self._announce_reminder(payload)
            except Exception as exc:  # keep the assistant alive no matter what
                log.exception("Task failed: %s", exc)
                self.emit("error", message=f"Something went wrong: {exc}")
                self._speak_safe("I'm afraid something went wrong, sir.")
            finally:
                self._task_active.clear()
                self._queue.task_done()
                if self._queue.empty() and not self._speaking.is_set():
                    self.set_state("idle")
                    self.audio.resume()

    def _process_audio(self, audio: np.ndarray) -> None:
        self.set_state("transcribing", "Processing voice input")
        try:
            text = self.stt.transcribe(audio)
        except Exception as exc:
            log.exception("Transcription failed")
            self.emit("error", message=f"Transcription failed: {exc}")
            self._speak_safe("I couldn't transcribe that, sir.")
            return
        if not text:
            self.emit("toast", level="warn", text="I didn't catch that.")
            self.set_state("idle")
            return
        text = self._strip_wake_phrase(text)
        self.emit("heard", text=text)
        self._process_text(text, source="voice")

    @staticmethod
    def _strip_wake_phrase(text: str) -> str:
        cleaned = text.strip()
        lowered = cleaned.lower()
        for phrase in ("hey jarvis,", "hey jarvis", "jarvis,"):
            if lowered.startswith(phrase):
                cleaned = cleaned[len(phrase) :].strip(" ,.:;!?-")
                break
        return cleaned

    # -------------------------------------------------------------- conversation
    def _build_system_prompt(self) -> str:
        facts = self.memory.facts()
        fact_lines = "\n".join(f"- {fact['key']}: {fact['value']}" for fact in facts[:60])
        notes = self.memory.search_notes("", limit=8)
        note_lines = "\n".join(f"- {note['title']}" for note in notes)
        now = datetime.now().astimezone().strftime("%A, %d %B %Y, %H:%M")
        prompt = PERSONA.format(
            user_name=self.settings.get("user_name", "sir"),
            now=now,
            city=self.settings.get("city", "London"),
        )
        prompt += "\n\nPersistent facts about the user:\n" + (fact_lines or "- none yet")
        prompt += "\n\nRecent note titles:\n" + (note_lines or "- none")
        prompt += (
            "\n\nAvailable capabilities: weather, web search, news, open apps/URLs/folders, "
            "system status, volume and media control, screenshots, clipboard, window control, "
            "lock PC, power control, reminders, notes, and long-term memory. "
            "Use tools whenever they would make the answer accurate or perform the action."
        )
        return prompt

    def _build_messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": self._build_system_prompt()}]
        for item in self.memory.recent_messages(limit=20):
            if item["content"].strip():
                messages.append({"role": item["role"], "content": item["content"]})
        return messages

    def _process_text(self, text: str, source: str = "ui", speak: bool | None = None) -> str:
        text = text.strip()
        if not text:
            return ""
        self.audio.pause()
        self._cancel.clear()
        self.set_state("thinking", "Reasoning")
        self.emit("user", text=text, source=source)
        self.memory.add_message("user", text)

        messages = self._build_messages()
        model = self.settings.get("model") or self.llm.default_model
        started = time.time()
        total_usage: dict[str, Any] = {}
        tool_count = 0
        final_text = ""
        last_tool_summary = ""

        for round_index in range(MAX_TOOL_ROUNDS):
            if self._cancel.is_set():
                break
            message_id = uuid.uuid4().hex[:12]
            emitted_any = False

            def on_text(delta: str, mid: str = message_id) -> None:
                nonlocal emitted_any
                emitted_any = True
                self.emit("assistant_delta", id=mid, text=delta)

            try:
                result = self.llm.stream_chat(
                    messages,
                    tools=self.toolbox.schemas,
                    model=model,
                    on_text=on_text,
                    cancel_event=self._cancel,
                )
            except OpenRouterError as exc:
                if emitted_any:
                    self.emit("assistant_discard", id=message_id)
                log.warning("OpenRouter error: %s", exc)
                self.emit("error", message=str(exc))
                self._speak_safe("I'm having trouble reaching my language core, sir.")
                self.set_state("idle")
                return ""
            except Exception as exc:
                if emitted_any:
                    self.emit("assistant_discard", id=message_id)
                log.exception("LLM failure")
                self.emit("error", message=f"Language core error: {exc}")
                self._speak_safe("I'm afraid my language core encountered an error, sir.")
                self.set_state("idle")
                return ""

            if result.get("usage"):
                total_usage = result["usage"]
            content = result.get("content", "")
            calls = result.get("tool_calls") or []

            if calls:
                if emitted_any:
                    self.emit("assistant_discard", id=message_id)
                messages.append(
                    {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": calls,
                    }
                )
                for call in calls:
                    tool_count += 1
                    name = call["function"].get("name", "")
                    raw_args = call["function"].get("arguments") or "{}"
                    try:
                        parsed_args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        parsed_args = {"_raw": raw_args}
                    call_id = call.get("id", "")
                    self.emit("tool_call", id=call_id, name=name, arguments=parsed_args)
                    self.set_state("thinking", f"Running {name.replace('_', ' ')}")
                    tool_started = time.time()
                    outcome = self.toolbox.execute(name, raw_args)
                    duration = round(time.time() - tool_started, 2)
                    summary = outcome.get("message", "")
                    last_tool_summary = summary
                    self.emit(
                        "tool_result",
                        id=call_id,
                        name=name,
                        ok=bool(outcome.get("ok")),
                        message=summary,
                        artifact=outcome.get("artifact"),
                        duration=duration,
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": json.dumps(outcome, ensure_ascii=False)[:8000],
                        }
                    )
                continue

            final_text = content.strip()
            if final_text:
                self.emit("assistant_done", id=message_id, text=final_text, source=source, model=model)
            else:
                self.emit("assistant_discard", id=message_id)
            break
        else:
            final_text = "I've completed the requested actions, sir."
            self.emit("assistant_done", id=uuid.uuid4().hex[:12], text=final_text, source=source, model=model)

        if self._cancel.is_set():
            self.set_state("idle", "Stopped")
            self.audio.resume()
            return final_text

        if not final_text:
            if tool_count and last_tool_summary:
                final_text = last_tool_summary
            else:
                final_text = "I'm not certain how to answer that, sir."
            self.emit("assistant_done", id=uuid.uuid4().hex[:12], text=final_text, source=source, model=model)

        self.memory.add_message("assistant", final_text)
        elapsed = round(time.time() - started, 2)
        self.emit("turn_complete", elapsed=elapsed, tool_count=tool_count, usage=total_usage, model=model)

        should_speak = self.settings.get("speak_replies", True) if speak is None else speak
        if should_speak:
            self._speak(final_text)
        else:
            self.set_state("idle")
            self.audio.resume()
        return final_text

    # ------------------------------------------------------------------- output
    def _tts_state(self, speaking: bool) -> None:
        self._speaking.set() if speaking else self._speaking.clear()

    def _speak(self, text: str) -> None:
        if not text:
            return
        self.audio.pause()
        self.set_state("speaking", "Responding")
        try:
            self.tts.speak(
                text,
                voice=self.settings.get("voice", "en-GB-RyanNeural"),
                rate=self.settings.get("rate", "+0%"),
                volume=self.settings.get("volume", "+0%"),
                on_start=lambda: self.emit("speech_start", text=text),
                on_end=lambda: self.emit("speech_end"),
            )
        finally:
            self._speaking.clear()
            self.set_state("idle")
            self.audio.resume()

    def _speak_safe(self, text: str) -> None:
        if not self.settings.get("speak_replies", True):
            return
        try:
            self._speak(text)
        except Exception:
            pass

    def stop(self) -> None:
        self._cancel.set()
        self.tts.stop()
        self.set_state("idle", "Stopped")
        self.audio.resume()
        self.emit("speech_end")

    def _announce_reminder(self, reminder: dict[str, Any]) -> None:
        text = f"Reminder, {self.settings.get('user_name', 'sir')}: {reminder['text']}."
        self.emit("reminder", id=reminder["id"], text=reminder["text"])
        self.emit("assistant_done", id=uuid.uuid4().hex[:12], text=text, source="reminder", model=None)
        self.memory.add_message("assistant", text)
        if self.settings.get("speak_replies", True):
            self._speak(text)
        else:
            self.set_state("idle")

    # ----------------------------------------------------------------- settings
    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        allowed = set(DEFAULT_SETTINGS)
        updated: dict[str, Any] = {}
        for key, value in (changes or {}).items():
            if key not in allowed:
                continue
            if key in {"wake_enabled", "speak_replies"}:
                value = bool(value)
            elif key == "wake_threshold":
                try:
                    value = max(0.2, min(0.95, float(value)))
                except (TypeError, ValueError):
                    continue
            elif key in {"voice", "model", "city", "user_name", "rate", "volume"}:
                value = str(value).strip()
                if not value:
                    continue
            self.memory.set_setting(key, value)
            self.settings[key] = value
            updated[key] = value
        if "model" in updated:
            self.llm.default_model = self.settings["model"]
        self.emit("settings", settings=self.settings)
        self.set_state(self.state, self._state_detail)
        return self.settings

    # ------------------------------------------------------------------ snapshot
    def history(self, limit: int = 40) -> list[dict[str, Any]]:
        return self.memory.recent_messages(limit=limit)

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": "1.0.0",
            "state": self.state,
            "settings": self.settings,
            "stats": self.memory.stats(),
            "history": self.history(40),
            "reminders": [
                {
                    "id": item["id"],
                    "text": item["text"],
                    "due": datetime.fromtimestamp(item["due_at"]).strftime("%a %d %b · %H:%M"),
                }
                for item in self.memory.reminders()
            ],
            "audio": {
                "available": self.audio.available,
                "error": self.audio.last_error,
                "recording": self.audio.recording,
            },
            "llm": {
                "configured": self.llm.configured,
                "model": self.settings.get("model"),
                "base_url": OPENROUTER_BASE_URL,
            },
            "stt": {"ready": self.stt.ready, "model": self.stt.model_name},
            "voices": VOICES,
            "quick_prompts": QUICK_PROMPTS,
            "paths": {"data": str(DATA_DIR), "config": str(CONFIG_FILE)},
            "uptime": int(time.time() - self.started_at),
        }

    def clear_history(self) -> None:
        self.memory.clear_messages()
        self.emit("history_cleared")
