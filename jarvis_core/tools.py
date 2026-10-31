"""J.A.R.V.I.S. toolbelt: web, weather, PC control, memory, notes, reminders."""

from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import subprocess
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import psutil
import requests
from PIL import ImageGrab

from .config import CACHE_DIR, SCREENSHOT_DIR
from .memory import Memory

USER_AGENT = "JARVIS/1.0 (Windows; local assistant)"

WEATHER_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "light rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "light snow",
    73: "moderate snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "light snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with light hail",
    99: "thunderstorm with heavy hail",
}

APP_ALIASES = {
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "calc": ["calc.exe"],
    "paint": ["mspaint.exe"],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "cmd": ["cmd.exe"],
    "command prompt": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "terminal": ["wt.exe"],
    "task manager": ["taskmgr.exe"],
    "control panel": ["control.exe"],
    "snipping tool": ["snippingtool.exe"],
    "settings": ["ms-settings:"],
    "spotify": ["spotify:"],
    "edge": ["microsoft-edge:"],
    "browser": ["microsoft-edge:"],
    "word": ["winword.exe"],
    "excel": ["excel.exe"],
    "powerpoint": ["powerpnt.exe"],
    "vscode": ["code.cmd"],
    "visual studio code": ["code.cmd"],
    "steam": ["steam://open/main"],
    "discord": ["discord:"],
    "camera": ["microsoft.windows.camera:"],
    "photos": ["ms-photos:"],
}


def _ok(message: str, **data: Any) -> dict[str, Any]:
    return {"ok": True, "message": message, **data}


def _err(message: str, **data: Any) -> dict[str, Any]:
    return {"ok": False, "message": message, **data}


def _pretty_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%A %d %B at %H:%M")


class Toolbox:
    def __init__(self, memory: Memory, settings_getter: Callable[[], dict[str, Any]]) -> None:
        self.memory = memory
        self.settings = settings_getter
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "get_datetime": self.get_datetime,
            "get_weather": self.get_weather,
            "web_search": self.web_search,
            "get_news": self.get_news,
            "open_app": self.open_app,
            "open_url": self.open_url,
            "open_folder": self.open_folder,
            "system_status": self.system_status,
            "control_volume": self.control_volume,
            "media_control": self.media_control,
            "take_screenshot": self.take_screenshot,
            "clipboard": self.clipboard,
            "lock_pc": self.lock_pc,
            "power_control": self.power_control,
            "window_control": self.window_control,
            "play_music": self.play_music,
            "set_reminder": self.set_reminder,
            "list_reminders": self.list_reminders,
            "cancel_reminder": self.cancel_reminder,
            "save_note": self.save_note,
            "search_notes": self.search_notes,
            "delete_note": self.delete_note,
            "remember_fact": self.remember_fact,
            "recall_facts": self.recall_facts,
            "forget_fact": self.forget_fact,
        }

    # ------------------------------------------------------------------ registry
    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [schema for schema, _ in TOOL_SCHEMAS]

    def execute(self, name: str, arguments: str | dict[str, Any]) -> dict[str, Any]:
        handler = self._handlers.get(name)
        if handler is None:
            return _err(f"Unknown tool '{name}'.")
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError as exc:
                return _err(f"Invalid tool arguments: {exc}")
        else:
            parsed = arguments or {}
        try:
            result = handler(parsed)
            if not isinstance(result, dict):
                return _ok(str(result))
            return result
        except Exception as exc:  # tools must never crash the assistant
            return _err(f"{name} failed: {exc}")

    # --------------------------------------------------------------------- time
    def get_datetime(self, args: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now().astimezone()
        return _ok(
            now.strftime("%A, %d %B %Y at %H:%M"),
            date=now.strftime("%Y-%m-%d"),
            time=now.strftime("%H:%M:%S"),
            weekday=now.strftime("%A"),
            timezone=str(now.tzinfo),
            iso=now.isoformat(),
        )

    # ------------------------------------------------------------------ weather
    def _geocode(self, location: str) -> dict[str, Any] | None:
        response = self._session.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1, "language": "en", "format": "json"},
            timeout=12,
        )
        response.raise_for_status()
        results = response.json().get("results") or []
        return results[0] if results else None

    def get_weather(self, args: dict[str, Any]) -> dict[str, Any]:
        location = str(args.get("location") or self.settings().get("city") or "London").strip()
        days = max(1, min(int(args.get("days", 1)), 5))
        place = self._geocode(location)
        if not place:
            return _err(f"I couldn't find a place called {location}.")
        response = self._session.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                "precipitation,weather_code,wind_speed_10m,is_day",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max",
                "timezone": "auto",
                "forecast_days": days,
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        current = payload.get("current", {})
        daily = payload.get("daily", {})
        condition = WEATHER_CODES.get(int(current.get("weather_code", -1)), "unknown conditions")
        forecast = []
        for index, date in enumerate(daily.get("time", [])[:days]):
            code = int(daily["weather_code"][index])
            forecast.append(
                {
                    "date": date,
                    "condition": WEATHER_CODES.get(code, "unknown"),
                    "high_c": daily["temperature_2m_max"][index],
                    "low_c": daily["temperature_2m_min"][index],
                    "rain_chance_pct": daily["precipitation_probability_max"][index],
                }
            )
        display = ", ".join(filter(None, [place.get("name"), place.get("admin1"), place.get("country")]))
        summary = (
            f"{display}: {condition}, {current.get('temperature_2m')}°C "
            f"(feels like {current.get('apparent_temperature')}°C), "
            f"humidity {current.get('relative_humidity_2m')}%, "
            f"wind {current.get('wind_speed_10m')} km/h."
        )
        return _ok(
            summary,
            location=display,
            current={
                "temperature_c": current.get("temperature_2m"),
                "feels_like_c": current.get("apparent_temperature"),
                "condition": condition,
                "humidity_pct": current.get("relative_humidity_2m"),
                "wind_kmh": current.get("wind_speed_10m"),
                "precipitation_mm": current.get("precipitation"),
            },
            forecast=forecast,
        )

    # --------------------------------------------------------------------- web
    def web_search(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query", "")).strip()
        if not query:
            return _err("A search query is required.")
        count = max(1, min(int(args.get("max_results", 5)), 10))
        from ddgs import DDGS

        results = DDGS().text(query, max_results=count)
        cleaned = [
            {
                "title": item.get("title", ""),
                "url": item.get("href") or item.get("url", ""),
                "snippet": (item.get("body") or "")[:500],
            }
            for item in results
        ]
        if not cleaned:
            return _err(f"No search results for '{query}'.")
        return _ok(f"Found {len(cleaned)} results for '{query}'.", results=cleaned)

    def get_news(self, args: dict[str, Any]) -> dict[str, Any]:
        topic = str(args.get("topic") or "top stories").strip()
        count = max(1, min(int(args.get("max_results", 6)), 10))
        from ddgs import DDGS

        try:
            results = DDGS().news(query=topic, max_results=count)
            cleaned = [
                {
                    "title": item.get("title", ""),
                    "source": item.get("source", ""),
                    "date": item.get("date", ""),
                    "url": item.get("url", ""),
                    "snippet": (item.get("body") or "")[:400],
                }
                for item in results
            ]
            if cleaned:
                return _ok(f"Latest headlines for {topic}.", results=cleaned)
        except Exception:
            pass

        # Fallback: BBC News RSS
        import feedparser

        feed = feedparser.parse("https://feeds.bbci.co.uk/news/rss.xml")
        entries = feed.entries[:count]
        if not entries:
            return _err("The news feeds are unreachable at the moment.")
        cleaned = [
            {
                "title": entry.get("title", ""),
                "source": "BBC News",
                "date": entry.get("published", ""),
                "url": entry.get("link", ""),
                "snippet": entry.get("summary", "")[:400],
            }
            for entry in entries
        ]
        return _ok("Latest headlines from BBC News.", results=cleaned)

    # ---------------------------------------------------------------- launching
    def _launch(self, command: str) -> None:
        if command.endswith(":") or "://" in command:
            os.startfile(command)  # type: ignore[attr-defined]
            return
        resolved = shutil.which(command)
        executable = resolved or command
        subprocess.Popen(
            [executable],
            close_fds=True,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )

    def open_app(self, args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("name", "")).strip().lower()
        if not name:
            return _err("An application name is required.")
        command = APP_ALIASES.get(name)
        if command:
            self._launch(command[0])
            return _ok(f"Opening {name}.")
        resolved = shutil.which(name)
        if resolved:
            subprocess.Popen(
                [resolved],
                close_fds=True,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            return _ok(f"Opening {name}.")
        return _err(f"I don't have a launch command for '{name}'.")

    def open_url(self, args: dict[str, Any]) -> dict[str, Any]:
        url = str(args.get("url", "")).strip()
        if not url:
            return _err("A URL is required.")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        webbrowser.open(url)
        return _ok(f"Opening {url}.")

    def open_folder(self, args: dict[str, Any]) -> dict[str, Any]:
        raw = str(args.get("path", "")).strip()
        if not raw:
            return _err("A path is required.")
        path = Path(os.path.expandvars(os.path.expanduser(raw)))
        if not path.exists():
            return _err(f"Path not found: {path}")
        os.startfile(str(path))  # type: ignore[attr-defined]
        return _ok(f"Opening {path}.")

    # ------------------------------------------------------------------- system
    def system_status(self, args: dict[str, Any]) -> dict[str, Any]:
        cpu = psutil.cpu_percent(interval=0.35)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
        battery = psutil.sensors_battery()
        uptime_seconds = time.time() - psutil.boot_time()
        hours, remainder = divmod(int(uptime_seconds), 3600)
        minutes = remainder // 60
        battery_text = "mains power"
        if battery:
            state = "charging" if battery.power_plugged else "on battery"
            battery_text = f"{battery.percent:.0f}% ({state})"
        summary = (
            f"CPU {cpu:.0f}%, memory {memory.percent:.0f}% used "
            f"({memory.used / 1024**3:.1f} of {memory.total / 1024**3:.1f} GB), "
            f"disk {disk.percent:.0f}% used, {battery_text}, "
            f"uptime {hours}h {minutes}m."
        )
        return _ok(
            summary,
            cpu_pct=round(cpu, 1),
            memory_pct=round(memory.percent, 1),
            memory_used_gb=round(memory.used / 1024**3, 2),
            memory_total_gb=round(memory.total / 1024**3, 2),
            disk_pct=round(disk.percent, 1),
            disk_free_gb=round(disk.free / 1024**3, 1),
            battery=battery_text,
            uptime_seconds=int(uptime_seconds),
            processes=len(psutil.pids()),
        )

    def _volume_interface(self) -> Any:
        from comtypes import CLSCTX_ALL, cast
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        speakers = AudioUtilities.GetSpeakers()
        # pycaw >= 2026 exposes the endpoint directly; older releases require
        # activating the COM interface manually.
        endpoint = getattr(speakers, "EndpointVolume", None)
        if endpoint is not None:
            return endpoint
        interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, ctypes.POINTER(IAudioEndpointVolume))

    def control_volume(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action", "set")).lower()
        volume = self._volume_interface()
        if action == "mute":
            volume.SetMute(1, None)
        elif action == "unmute":
            volume.SetMute(0, None)
        elif action in {"up", "down"}:
            step = 0.1 if action == "up" else -0.1
            level = max(0.0, min(1.0, volume.GetMasterVolumeLevelScalar() + step))
            volume.SetMasterVolumeLevelScalar(level, None)
        else:
            level = max(0.0, min(100.0, float(args.get("level", 50)))) / 100.0
            volume.SetMasterVolumeLevelScalar(level, None)
            volume.SetMute(0, None)
        current = round(volume.GetMasterVolumeLevelScalar() * 100)
        muted = bool(volume.GetMute())
        return _ok(f"Volume is now {current}%{' and muted' if muted else ''}.", level=current, muted=muted)

    def media_control(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action", "play_pause")).lower()
        keys = {
            "play_pause": 0xB3,
            "next": 0xB0,
            "previous": 0xB1,
            "prev": 0xB1,
            "stop": 0xB2,
        }
        if action not in keys:
            return _err(f"Unknown media action '{action}'.")
        vk = keys[action]
        user32 = ctypes.windll.user32
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)
        return _ok(f"Media command sent: {action.replace('_', ' ')}.")

    def take_screenshot(self, args: dict[str, Any]) -> dict[str, Any]:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = SCREENSHOT_DIR / f"jarvis_{stamp}.png"
        image = ImageGrab.grab(all_screens=True)
        image.save(path)
        width, height = image.size
        return _ok(
            f"Screenshot captured ({width} by {height}).",
            path=str(path),
            artifact={"kind": "screenshot", "url": f"/api/screenshots/{path.name}", "name": path.name},
        )

    def clipboard(self, args: dict[str, Any]) -> dict[str, Any]:
        import pyperclip

        action = str(args.get("action", "get")).lower()
        if action == "set":
            text = str(args.get("text", ""))
            pyperclip.copy(text)
            return _ok("Copied to the clipboard.")
        content = pyperclip.paste()
        return _ok("Clipboard read.", text=content[:4000])

    def lock_pc(self, args: dict[str, Any]) -> dict[str, Any]:
        ctypes.windll.user32.LockWorkStation()
        return _ok("Locking the workstation.")

    def power_control(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action", "")).lower()
        confirm = bool(args.get("confirm", False))
        if not confirm:
            return _err("Power actions require explicit confirmation. Ask the user first.")
        if action == "cancel":
            subprocess.run(["shutdown", "/a"], capture_output=True, check=False)
            return _ok("Scheduled shutdown cancelled.")
        if action == "shutdown":
            subprocess.run(["shutdown", "/s", "/t", "45"], capture_output=True, check=False)
            return _ok("Shutting down in 45 seconds. Say cancel to abort.")
        if action == "restart":
            subprocess.run(["shutdown", "/r", "/t", "45"], capture_output=True, check=False)
            return _ok("Restarting in 45 seconds.")
        if action == "sleep":
            subprocess.run(
                ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                capture_output=True,
                check=False,
            )
            return _ok("Entering sleep mode.")
        return _err(f"Unknown power action '{action}'.")

    def window_control(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action", "")).lower()
        user32 = ctypes.windll.user32
        if action == "minimize_all":
            user32.keybd_event(0x5B, 0, 0, 0)
            user32.keybd_event(0x44, 0, 0, 0)
            user32.keybd_event(0x44, 0, 2, 0)
            user32.keybd_event(0x5B, 0, 2, 0)
            return _ok("Minimising all windows.")
        if action == "switch_window":
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x09, 0, 0, 0)
            user32.keybd_event(0x09, 0, 2, 0)
            user32.keybd_event(0x12, 0, 2, 0)
            return _ok("Switching windows.")
        if action == "task_view":
            user32.keybd_event(0x5B, 0, 0, 0)
            user32.keybd_event(0x09, 0, 0, 0)
            user32.keybd_event(0x09, 0, 2, 0)
            user32.keybd_event(0x5B, 0, 2, 0)
            return _ok("Opening task view.")
        return _err(f"Unknown window action '{action}'.")

    def play_music(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query") or "focus music").strip()
        url = "https://www.youtube.com/results?search_query=" + requests.utils.quote(query)
        webbrowser.open(url)
        return _ok(f"Searching YouTube for {query}.")

    # ---------------------------------------------------------------- reminders
    def set_reminder(self, args: dict[str, Any]) -> dict[str, Any]:
        text = str(args.get("text", "")).strip()
        when = str(args.get("when", "")).strip()
        if not text or not when:
            return _err("Both the reminder text and a time are required.")
        import dateparser

        parsed = dateparser.parse(
            when,
            settings={
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": datetime.now(),
                "RETURN_AS_TIMEZONE_AWARE": False,
            },
        )
        if parsed is None:
            return _err(f"I couldn't understand the time '{when}'.")
        timestamp = parsed.timestamp()
        if timestamp <= time.time() + 1:
            return _err("That time is in the past.")
        reminder_id = self.memory.add_reminder(text, timestamp)
        return _ok(
            f"Reminder set for {_pretty_time(timestamp)}: {text}.",
            id=reminder_id,
            due=_pretty_time(timestamp),
            due_iso=parsed.isoformat(),
        )

    def list_reminders(self, args: dict[str, Any]) -> dict[str, Any]:
        reminders = self.memory.reminders()
        if not reminders:
            return _ok("There are no active reminders.")
        items = [
            {"id": item["id"], "text": item["text"], "due": _pretty_time(item["due_at"])}
            for item in reminders
        ]
        listing = "; ".join(f"#{item['id']} {item['text']} — {item['due']}" for item in items)
        return _ok(f"{len(items)} active reminder(s): {listing}", reminders=items)

    def cancel_reminder(self, args: dict[str, Any]) -> dict[str, Any]:
        reminder_id = args.get("id")
        text = args.get("text")
        count = self.memory.cancel_reminder(
            int(reminder_id) if reminder_id not in (None, "") else None,
            str(text) if text else None,
        )
        if not count:
            return _err("No matching active reminder was found.")
        return _ok(f"Cancelled {count} reminder(s).")

    # -------------------------------------------------------------------- notes
    def save_note(self, args: dict[str, Any]) -> dict[str, Any]:
        title = str(args.get("title") or "Untitled note").strip()
        content = str(args.get("content", "")).strip()
        if not content:
            return _err("The note is empty.")
        note_id = self.memory.add_note(title, content)
        return _ok(f"Note '{title}' saved.", id=note_id)

    def search_notes(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query", "")).strip()
        notes = self.memory.search_notes(query)
        if not notes:
            return _ok("No matching notes." if query else "There are no notes.")
        compact = [
            {"id": note["id"], "title": note["title"], "content": note["content"][:600]}
            for note in notes
        ]
        return _ok(f"Found {len(compact)} note(s).", notes=compact)

    def delete_note(self, args: dict[str, Any]) -> dict[str, Any]:
        note_id = args.get("id")
        if note_id in (None, ""):
            return _err("A note id is required.")
        return _ok("Note deleted.") if self.memory.delete_note(int(note_id)) else _err("Note not found.")

    # ------------------------------------------------------------------- memory
    def remember_fact(self, args: dict[str, Any]) -> dict[str, Any]:
        key = str(args.get("key", "")).strip()
        value = str(args.get("value", "")).strip()
        if not key or not value:
            return _err("Both key and value are required.")
        self.memory.set_fact(key, value)
        return _ok(f"Remembered: {key} — {value}.")

    def recall_facts(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query", "")).strip()
        facts = self.memory.facts(query or None)
        if not facts:
            return _ok("I have no matching memories.")
        return _ok(
            f"Recalled {len(facts)} fact(s).",
            facts=facts,
        )

    def forget_fact(self, args: dict[str, Any]) -> dict[str, Any]:
        key = str(args.get("key", "")).strip()
        if not key:
            return _err("A memory key is required.")
        return _ok(f"Forgotten: {key}.") if self.memory.forget_fact(key) else _err("No such memory.")


def _schema(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


TOOL_SCHEMAS: list[tuple[dict[str, Any], Callable]] = [
    (
        _schema(
            "get_datetime",
            "Get the current local date, time, weekday, and timezone.",
            {},
        ),
        Toolbox.get_datetime,
    ),
    (
        _schema(
            "get_weather",
            "Get current weather and a short forecast for a city. Use when the user asks about weather.",
            {
                "location": {"type": "string", "description": "City or place. Defaults to the user's configured city."},
                "days": {"type": "integer", "minimum": 1, "maximum": 5, "description": "Forecast days, default 1."},
            },
        ),
        Toolbox.get_weather,
    ),
    (
        _schema(
            "web_search",
            "Search the live web for facts, prices, people, products, or current information.",
            {
                "query": {"type": "string", "description": "Search query."},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            },
            ["query"],
        ),
        Toolbox.web_search,
    ),
    (
        _schema(
            "get_news",
            "Get current news headlines, optionally on a topic.",
            {
                "topic": {"type": "string", "description": "Topic, e.g. technology, AI, world news. Defaults to top stories."},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 10, "default": 6},
            },
        ),
        Toolbox.get_news,
    ),
    (
        _schema(
            "open_app",
            "Open a desktop application such as notepad, calculator, explorer, settings, spotify, edge, word, excel, or vscode.",
            {"name": {"type": "string", "description": "Application name."}},
            ["name"],
        ),
        Toolbox.open_app,
    ),
    (
        _schema(
            "open_url",
            "Open a web page in the default browser.",
            {"url": {"type": "string", "description": "Full URL or domain."}},
            ["url"],
        ),
        Toolbox.open_url,
    ),
    (
        _schema(
            "open_folder",
            "Open a folder or file in Windows Explorer.",
            {"path": {"type": "string", "description": "Absolute or user-relative path."}},
            ["path"],
        ),
        Toolbox.open_folder,
    ),
    (
        _schema(
            "system_status",
            "Read CPU, memory, disk, battery, uptime, and process count.",
            {},
        ),
        Toolbox.system_status,
    ),
    (
        _schema(
            "control_volume",
            "Set, raise, lower, mute, or unmute the system volume.",
            {
                "action": {"type": "string", "enum": ["set", "up", "down", "mute", "unmute"], "default": "set"},
                "level": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Target volume for action=set."},
            },
        ),
        Toolbox.control_volume,
    ),
    (
        _schema(
            "media_control",
            "Control the active media player: play/pause, next, previous, or stop.",
            {"action": {"type": "string", "enum": ["play_pause", "next", "previous", "stop"], "default": "play_pause"}},
        ),
        Toolbox.media_control,
    ),
    (
        _schema(
            "take_screenshot",
            "Capture all monitors and save a screenshot. The HUD can display the captured image.",
            {},
        ),
        Toolbox.take_screenshot,
    ),
    (
        _schema(
            "clipboard",
            "Read the clipboard or copy text to it.",
            {
                "action": {"type": "string", "enum": ["get", "set"], "default": "get"},
                "text": {"type": "string", "description": "Text to copy when action=set."},
            },
        ),
        Toolbox.clipboard,
    ),
    (
        _schema("lock_pc", "Lock the Windows workstation.", {}),
        Toolbox.lock_pc,
    ),
    (
        _schema(
            "power_control",
            "Shut down, restart, sleep, or cancel a scheduled shutdown. Only after explicit user confirmation.",
            {
                "action": {"type": "string", "enum": ["shutdown", "restart", "sleep", "cancel"]},
                "confirm": {"type": "boolean", "description": "Must be true only after the user explicitly confirmed."},
            },
            ["action", "confirm"],
        ),
        Toolbox.power_control,
    ),
    (
        _schema(
            "window_control",
            "Arrange windows: minimize all, switch window, or open task view.",
            {"action": {"type": "string", "enum": ["minimize_all", "switch_window", "task_view"]}},
            ["action"],
        ),
        Toolbox.window_control,
    ),
    (
        _schema(
            "play_music",
            "Open a YouTube search for music to play.",
            {"query": {"type": "string", "description": "Artist, song, genre, or mood."}},
            ["query"],
        ),
        Toolbox.play_music,
    ),
    (
        _schema(
            "set_reminder",
            "Create a spoken reminder. Use natural language times such as 'in 20 minutes', 'tomorrow at 9am', or 'at 18:30'.",
            {
                "text": {"type": "string", "description": "What to remind the user about."},
                "when": {"type": "string", "description": "Natural-language date/time."},
            },
            ["text", "when"],
        ),
        Toolbox.set_reminder,
    ),
    (
        _schema("list_reminders", "List active reminders.", {}),
        Toolbox.list_reminders,
    ),
    (
        _schema(
            "cancel_reminder",
            "Cancel an active reminder by id or matching text.",
            {
                "id": {"type": "integer", "description": "Reminder id."},
                "text": {"type": "string", "description": "Text to match instead of id."},
            },
        ),
        Toolbox.cancel_reminder,
    ),
    (
        _schema(
            "save_note",
            "Save a durable note in the local database.",
            {
                "title": {"type": "string"},
                "content": {"type": "string"},
            },
            ["title", "content"],
        ),
        Toolbox.save_note,
    ),
    (
        _schema(
            "search_notes",
            "Search saved notes by keyword, or list recent notes.",
            {"query": {"type": "string", "description": "Keyword; omit to list recent notes."}},
        ),
        Toolbox.search_notes,
    ),
    (
        _schema(
            "delete_note",
            "Delete a note by id.",
            {"id": {"type": "integer"}},
            ["id"],
        ),
        Toolbox.delete_note,
    ),
    (
        _schema(
            "remember_fact",
            "Store a durable fact or preference about the user, e.g. key='favourite tea', value='Earl Grey'.",
            {
                "key": {"type": "string"},
                "value": {"type": "string"},
            },
            ["key", "value"],
        ),
        Toolbox.remember_fact,
    ),
    (
        _schema(
            "recall_facts",
            "Recall stored facts, optionally filtered by keyword.",
            {"query": {"type": "string"}},
        ),
        Toolbox.recall_facts,
    ),
    (
        _schema(
            "forget_fact",
            "Delete a stored fact by key.",
            {"key": {"type": "string"}},
            ["key"],
        ),
        Toolbox.forget_fact,
    ),
]
