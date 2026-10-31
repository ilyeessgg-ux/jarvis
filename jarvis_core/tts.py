"""British JARVIS voice: edge-tts synthesis, cached, with Windows SAPI fallback."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

import edge_tts
import imageio_ffmpeg
import sounddevice as sd
import soundfile as sf

from .config import CACHE_DIR

EMOJI_RE = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U00002700-\U000027BF" "\U0001F1E0-\U0001F1FF" "]+",
    flags=re.UNICODE,
)


def clean_for_speech(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "a link", text)
    text = re.sub(r"[*_#>`~|]", " ", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.MULTILINE)
    text = EMOJI_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class TTSEngine:
    def __init__(self, cache_dir: Path = CACHE_DIR) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._speaking = threading.Event()
        self.on_state: Callable[[bool], None] | None = None

    @property
    def speaking(self) -> bool:
        return self._speaking.is_set()

    def stop(self) -> None:
        self._stop.set()
        try:
            sd.stop()
        except Exception:
            pass

    def _cache_paths(self, text: str, voice: str, rate: str, volume: str) -> tuple[Path, Path]:
        digest = hashlib.sha1(f"{voice}|{rate}|{volume}|{text}".encode("utf-8")).hexdigest()[:20]
        return self.cache_dir / f"{digest}.mp3", self.cache_dir / f"{digest}.wav"

    async def _synthesise(self, text: str, voice: str, rate: str, volume: str, mp3_path: Path) -> None:
        communicate = edge_tts.Communicate(text, voice=voice, rate=rate, volume=volume)
        await communicate.save(str(mp3_path))

    def _to_wav(self, mp3_path: Path, wav_path: Path) -> None:
        subprocess.run(
            [
                self._ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(mp3_path),
                "-ac",
                "1",
                "-ar",
                "24000",
                str(wav_path),
            ],
            check=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )

    def _sapi_wav(self, text: str, wav_path: Path) -> None:
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        script = (
            "Add-Type -AssemblyName System.Speech; "
            f"$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}')); "
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.SetOutputToWaveFile('{wav_path}'); $s.Speak($t); $s.Dispose()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )

    def _play(self, wav_path: Path) -> None:
        data, samplerate = sf.read(str(wav_path), dtype="float32", always_2d=True)
        if data.size == 0:
            return
        duration = len(data) / samplerate
        sd.play(data, samplerate)
        started = time.time()
        while time.time() - started < duration + 0.15:
            if self._stop.is_set():
                sd.stop()
                break
            time.sleep(0.03)
        try:
            sd.stop()
        except Exception:
            pass

    def speak(
        self,
        text: str,
        voice: str,
        rate: str = "+0%",
        volume: str = "+0%",
        on_start: Callable[[], None] | None = None,
        on_end: Callable[[], None] | None = None,
    ) -> None:
        spoken = clean_for_speech(text)
        if not spoken:
            return
        with self._lock:
            self._stop.clear()
            self._speaking.set()
            if self.on_state:
                self.on_state(True)
            try:
                mp3_path, wav_path = self._cache_paths(spoken, voice, rate, volume)
                if not wav_path.exists():
                    try:
                        asyncio.run(self._synthesise(spoken, voice, rate, volume, mp3_path))
                        self._to_wav(mp3_path, wav_path)
                    except Exception:
                        try:
                            self._sapi_wav(spoken, wav_path)
                        except Exception:
                            return
                if self._stop.is_set():
                    return
                if on_start:
                    on_start()
                self._play(wav_path)
            finally:
                self._speaking.clear()
                if self.on_state:
                    self.on_state(False)
                if on_end:
                    on_end()
