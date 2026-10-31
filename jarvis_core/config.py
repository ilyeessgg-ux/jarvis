"""Configuration and persistent defaults for J.A.R.V.I.S."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

FROZEN = bool(getattr(sys, "frozen", False))

# Where the running application lives. In a packaged build this is the folder
# containing JARVIS.exe; during development it is the repository root.
APP_DIR = (
    Path(sys.executable).resolve().parent
    if FROZEN
    else Path(__file__).resolve().parent.parent
)
# Read-only resources shipped inside the PyInstaller bundle.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR)) if FROZEN else APP_DIR
BASE_DIR = APP_DIR  # backwards-compatible alias

# Writable state never lives inside the (possibly read-only) install folder.
if FROZEN:
    _default_data = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "JARVIS"
else:
    _default_data = APP_DIR / "data"

DATA_DIR = Path(os.getenv("JARVIS_DATA_DIR", str(_default_data))).expanduser()
MODELS_DIR = BUNDLE_DIR / "models"
WEB_DIR = BUNDLE_DIR / "web"
ASSETS_DIR = BUNDLE_DIR / "assets"
CACHE_DIR = DATA_DIR / "cache"
SCREENSHOT_DIR = DATA_DIR / "screenshots"
LOG_DIR = DATA_DIR / "logs"
WEBVIEW_DIR = DATA_DIR / "webview"

for _directory in (DATA_DIR, CACHE_DIR, SCREENSHOT_DIR, LOG_DIR):
    _directory.mkdir(parents=True, exist_ok=True)

# The .env can sit next to the executable or in the writable data folder.
# Existing environment variables always win (load_dotenv does not override).
for _env_file in (APP_DIR / ".env", DATA_DIR / ".env"):
    if _env_file.is_file():
        load_dotenv(_env_file, override=False)

CONFIG_FILE = APP_DIR / ".env" if (APP_DIR / ".env").is_file() else DATA_DIR / ".env"
if not CONFIG_FILE.is_file():
    CONFIG_FILE = DATA_DIR / ".env"


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


_raw_api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_API_KEY = (
    "" if _raw_api_key.lower() in {"your-openrouter-key-here", "changeme", "your-key"} else _raw_api_key
)
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini").strip()

HOST = os.getenv("JARVIS_HOST", "127.0.0.1")
PORT = int(os.getenv("JARVIS_PORT", "7777"))
WAKE_WORD = "hey jarvis"
WAKE_MODEL = MODELS_DIR / "openwakeword" / "hey_jarvis_v0.1.onnx"
MEL_MODEL = MODELS_DIR / "openwakeword" / "melspectrogram.onnx"
EMBEDDING_MODEL = MODELS_DIR / "openwakeword" / "embedding_model.onnx"
WHISPER_DIR = (DATA_DIR / "models" / "whisper") if FROZEN else (MODELS_DIR / "whisper")
WHISPER_MODEL = os.getenv("JARVIS_WHISPER_MODEL", "base.en")
WHISPER_MODEL_DIR = MODELS_DIR / "whisper" / WHISPER_MODEL
ICON_PATH = ASSETS_DIR / "jarvis.ico"
SAMPLE_RATE = 16_000

DEFAULT_SETTINGS: dict[str, object] = {
    "user_name": os.getenv("JARVIS_USER_NAME", "sir"),
    "city": os.getenv("JARVIS_CITY", "London"),
    "voice": os.getenv("JARVIS_VOICE", "en-GB-RyanNeural"),
    "model": OPENROUTER_MODEL,
    "wake_enabled": _bool("JARVIS_WAKE_ENABLED", True),
    "speak_replies": _bool("JARVIS_SPEAK_REPLIES", True),
    "wake_threshold": float(os.getenv("JARVIS_WAKE_THRESHOLD", "0.55")),
    "rate": os.getenv("JARVIS_VOICE_RATE", "+0%"),
    "volume": os.getenv("JARVIS_VOICE_VOLUME", "+0%"),
}

BOOLEAN_SETTINGS = {"wake_enabled", "speak_replies"}
FLOAT_SETTINGS = {"wake_threshold"}

VOICES = [
    {"id": "en-GB-RyanNeural", "label": "Ryan — British, calm (default)"},
    {"id": "en-GB-ThomasNeural", "label": "Thomas — British, warm"},
    {"id": "en-GB-SoniaNeural", "label": "Sonia — British, polished"},
    {"id": "en-GB-LibbyNeural", "label": "Libby — British, light"},
    {"id": "en-US-GuyNeural", "label": "Guy — American, deep"},
    {"id": "en-US-JennyNeural", "label": "Jenny — American, clear"},
    {"id": "en-AU-WilliamNeural", "label": "William — Australian"},
]

PERSONA = """You are J.A.R.V.I.S. (Just A Rather Very Intelligent System), the personal AI assistant of {user_name}.
Speak like the classic JARVIS: calm, precise, understated British wit, unfailingly competent. Address the user as "{user_name}" naturally — not in every sentence. Never grovel and never over-explain.

Rules:
- Replies are spoken aloud. Be concise: usually 1-3 sentences, no markdown, no bullet lists, no code blocks, no emoji, no stage directions.
- When a tool can answer or perform the request, call it rather than guessing. Never invent weather, news, system readings, or file paths.
- After tools run, summarise the useful result in natural speech.
- For destructive actions (shutdown, restart, sleep) require explicit confirmation first, then call the tool with confirm=true.
- If a request is ambiguous and guessing would be costly, ask one short clarifying question.
- You have persistent memory. Use remembered facts and notes when relevant, and save durable preferences when the user asks you to remember something.
- Current local date/time: {now}.
- User's city (for weather): {city}.
- Operating system: Windows.
"""

QUICK_PROMPTS = [
    "Brief me on my day",
    "What's the weather like?",
    "How is the system running?",
    "Take a screenshot",
    "What's in the news?",
    "Play some music",
]
