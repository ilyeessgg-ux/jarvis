"""Always-on microphone pipeline: openWakeWord + energy-based command recorder."""

from __future__ import annotations

import queue
import threading
import time
from typing import Callable

import numpy as np
import sounddevice as sd

from .config import EMBEDDING_MODEL, MEL_MODEL, SAMPLE_RATE, WAKE_MODEL

FRAME = 1280  # 80 ms at 16 kHz — openWakeWord's expected frame size


def _rms(frame: np.ndarray) -> float:
    if frame.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))


class AudioEngine:
    def __init__(
        self,
        settings_getter: Callable[[], dict],
        on_wake: Callable[[], None],
        on_command: Callable[[np.ndarray], None],
        on_level: Callable[[float], None],
        on_error: Callable[[str], None],
        on_state: Callable[[str], None],
    ) -> None:
        self._settings = settings_getter
        self._on_wake = on_wake
        self._on_command = on_command
        self._on_level = on_level
        self._on_error = on_error
        self._on_state = on_state

        self._frames: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._manual = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream: sd.InputStream | None = None
        self._wake_model = None
        self._noise_floor = 120.0
        self._last_wake = 0.0
        self._recording = threading.Event()
        self._last_level_emit = 0.0
        self._available = False
        self.last_error: str | None = None

    @property
    def available(self) -> bool:
        return self._available

    @property
    def recording(self) -> bool:
        return self._recording.is_set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="jarvis-audio", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=2.0)

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()
        self._drain()
        if self._wake_model is not None:
            try:
                self._wake_model.reset()
            except Exception:
                pass

    def request_listen(self) -> None:
        if self._paused.is_set() and not self._recording.is_set():
            self._paused.clear()
        self._manual.set()

    def _drain(self) -> None:
        while True:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                return

    def _load_wake_model(self) -> None:
        from openwakeword.model import Model

        self._wake_model = Model(
            wakeword_models=[str(WAKE_MODEL)],
            inference_framework="onnx",
            melspec_model_path=str(MEL_MODEL),
            embedding_model_path=str(EMBEDDING_MODEL),
        )

    def _audio_callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if status:
            pass
        frame = indata[:, 0].copy()
        try:
            self._frames.put_nowait(frame)
        except queue.Full:
            try:
                self._frames.get_nowait()
                self._frames.put_nowait(frame)
            except queue.Empty:
                pass
        level = min(1.0, _rms(frame) / 6000.0)
        now = time.time()
        if now - self._last_level_emit > 0.07:
            self._last_level_emit = now
            try:
                self._on_level(level)
            except Exception:
                pass

    def _run(self) -> None:
        try:
            self._load_wake_model()
        except Exception as exc:
            self.last_error = f"Wake-word model failed to load: {exc}"
            self._on_error(self.last_error)
            return

        try:
            device = self._settings().get("input_device") or None
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                blocksize=FRAME,
                channels=1,
                dtype="int16",
                callback=self._audio_callback,
                device=device,
            )
            self._stream.start()
            self._available = True
            self._on_state("armed")
        except Exception as exc:
            self.last_error = f"Microphone unavailable: {exc}"
            self._on_error(self.last_error)
            return

        try:
            self._loop()
        finally:
            self._available = False
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass

    def _loop(self) -> None:
        calibration_frames = 8
        calibrated = 0
        while not self._stop.is_set():
            try:
                frame = self._frames.get(timeout=0.25)
            except queue.Empty:
                continue

            level_rms = _rms(frame)
            if calibrated < calibration_frames:
                self._noise_floor = max(30.0, 0.7 * self._noise_floor + 0.3 * level_rms)
                calibrated += 1
                continue

            if not self._recording.is_set() and not self._paused.is_set():
                self._noise_floor = min(700.0, 0.995 * self._noise_floor + 0.005 * level_rms)

            if self._manual.is_set() and not self._recording.is_set():
                self._manual.clear()
                self._record_command()
                continue

            settings = self._settings()
            if (
                settings.get("wake_enabled", True)
                and not self._paused.is_set()
                and not self._recording.is_set()
                and self._wake_model is not None
                and time.time() - self._last_wake > 2.0
            ):
                try:
                    scores = self._wake_model.predict(frame)
                    score = max(scores.values()) if scores else 0.0
                except Exception:
                    score = 0.0
                threshold = float(settings.get("wake_threshold", 0.55))
                if score >= threshold:
                    self._last_wake = time.time()
                    self._recording.set()
                    try:
                        self._wake_model.reset()
                    except Exception:
                        pass
                    self._on_wake()
                    self._chime()
                    self._drain()
                    self._record_command()
                    self._recording.clear()
                    self.resume()

    def _chime(self) -> None:
        try:
            sr = 24_000
            first = np.sin(2 * np.pi * 740 * np.arange(int(sr * 0.09)) / sr)
            second = np.sin(2 * np.pi * 1108 * np.arange(int(sr * 0.13)) / sr)
            tone = np.concatenate([first, second]).astype(np.float32)
            fade = int(sr * 0.02)
            tone[:fade] *= np.linspace(0, 1, fade)
            tone[-fade:] *= np.linspace(1, 0, fade)
            sd.play(tone * 0.14, sr)
            sd.wait()
        except Exception:
            pass

    def _record_command(self) -> None:
        self._recording.set()
        self._on_state("recording")
        self._drain()
        threshold = max(260.0, self._noise_floor * 2.3)
        pre_roll: list[np.ndarray] = []
        collected: list[np.ndarray] = []
        speech_started = False
        speech_frames = 0
        silent_frames = 0
        waited_frames = 0
        max_wait_frames = int(5.0 / 0.08)
        max_silence_frames = int(1.15 / 0.08)
        max_frames = int(12.0 / 0.08)

        try:
            while not self._stop.is_set():
                try:
                    frame = self._frames.get(timeout=0.25)
                except queue.Empty:
                    if speech_started:
                        break
                    continue
                rms = _rms(frame)
                if not speech_started:
                    pre_roll.append(frame)
                    if len(pre_roll) > 5:
                        pre_roll.pop(0)
                    waited_frames += 1
                    if rms > threshold:
                        speech_started = True
                        collected.extend(pre_roll)
                        speech_frames += 1
                    elif waited_frames > max_wait_frames:
                        self._on_error("I didn't hear anything. Try again.")
                        return
                else:
                    collected.append(frame)
                    if rms > threshold * 0.82:
                        speech_frames += 1
                        silent_frames = 0
                    else:
                        silent_frames += 1
                    if silent_frames >= max_silence_frames and speech_frames >= 3:
                        break
                    if len(collected) >= max_frames:
                        break
            if not speech_started or speech_frames < 3:
                self._on_error("I didn't catch that. Try again.")
                return
            audio = np.concatenate(collected).astype(np.float32) / 32768.0
            self._on_command(audio)
        finally:
            self._recording.clear()
