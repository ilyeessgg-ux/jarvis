"""Download the local wake-word and speech-to-text models.

Run with the project's isolated runtime:
    .\\runtime\\python.exe download_models.py
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WAKE_DIR = ROOT / "models" / "openwakeword"
WHISPER_DIR = ROOT / "models" / "whisper"
WHISPER_FLAT_DIR = WHISPER_DIR / "base.en"

WAKE_FILES = {
    "melspectrogram.onnx": "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/melspectrogram.onnx",
    "embedding_model.onnx": "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/embedding_model.onnx",
    "hey_jarvis_v0.1.onnx": "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/hey_jarvis_v0.1.onnx",
}


def download(url: str, destination: Path) -> None:
    if destination.exists() and destination.stat().st_size > 100_000:
        print(f"  exists  {destination.name} ({destination.stat().st_size / 1024 / 1024:.1f} MB)")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"  fetch   {destination.name}")
    temporary = destination.with_suffix(destination.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as handle:
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            received += len(chunk)
            if total:
                print(f"\r          {received / total * 100:5.1f}%", end="", flush=True)
    print()
    temporary.replace(destination)
    print(f"  saved   {destination.name} ({destination.stat().st_size / 1024 / 1024:.1f} MB)")


def download_wake() -> None:
    print("openWakeWord - Hey Jarvis")
    for name, url in WAKE_FILES.items():
        download(url, WAKE_DIR / name)


def download_whisper() -> None:
    print("faster-whisper - base.en (local speech recognition)")
    try:
        from faster_whisper.utils import download_model
    except ImportError:
        print("  faster-whisper is not installed. Run setup.ps1 first.")
        raise SystemExit(1)

    if (WHISPER_FLAT_DIR / "model.bin").is_file():
        print(f"  exists  {WHISPER_FLAT_DIR}")
        return

    print("  loading / downloading model (first run may take a minute)...")
    # A flat directory is what PyInstaller bundles and what STTEngine loads,
    # and it avoids shipping the duplicated Hugging Face cache layout.
    download_model(
        "base.en",
        output_dir=str(WHISPER_FLAT_DIR),
        cache_dir=str(WHISPER_DIR),
    )
    print(f"  ready   {WHISPER_FLAT_DIR}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download JARVIS local models")
    parser.add_argument("--wake-only", action="store_true")
    parser.add_argument("--whisper-only", action="store_true")
    args = parser.parse_args()

    if not args.whisper_only:
        download_wake()
    if not args.wake_only:
        download_whisper()
    print("\nModels ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
