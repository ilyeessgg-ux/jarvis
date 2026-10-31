"""Local speech-to-text with faster-whisper."""

from __future__ import annotations

import threading
from typing import Any

import numpy as np

from .config import WHISPER_DIR, WHISPER_MODEL, WHISPER_MODEL_DIR


class STTEngine:
    def __init__(self, model_name: str = WHISPER_MODEL) -> None:
        self.model_name = model_name
        self._model: Any = None
        self._lock = threading.Lock()
        self._load_lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._model is not None

    def preload(self) -> None:
        self._ensure_model()

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                # Packaged builds ship a flat CTranslate2 model directory. Fall
                # back to the model name (and download cache) when it is absent.
                bundled = WHISPER_MODEL_DIR / "model.bin"
                model_ref = str(WHISPER_MODEL_DIR) if bundled.is_file() else self.model_name
                self._model = WhisperModel(
                    model_ref,
                    device="cpu",
                    compute_type="int8",
                    download_root=str(WHISPER_DIR),
                    cpu_threads=4,
                )
        return self._model

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16_000) -> str:
        if audio.size < sample_rate * 0.25:
            return ""
        model = self._ensure_model()
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        if np.abs(audio).max() > 1.5:
            audio = audio / 32768.0
        with self._lock:
            segments, _info = model.transcribe(
                audio,
                language="en",
                beam_size=1,
                best_of=1,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 400},
                condition_on_previous_text=False,
                without_timestamps=True,
            )
            text = " ".join(segment.text.strip() for segment in segments)
        return " ".join(text.split()).strip()
