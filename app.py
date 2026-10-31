"""J.A.R.V.I.S. entry point.

Usage:
    python app.py                 # server + default browser
    python app.py --window        # native desktop window (pywebview)
    python app.py --background    # tray app, window appears on "Hey Jarvis"
    python app.py --ask "..."     # one-shot text query, no UI/voice
    python app.py --say "..."     # speak a line through the JARVIS voice
    python app.py --diagnose      # environment / dependency report
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

# The embedded Python runtime keeps its own directory on sys.path, not the
# project root. Add this file's directory so `jarvis_core` resolves everywhere.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jarvis_core.config import (
    BUNDLE_DIR,
    CONFIG_FILE,
    DATA_DIR,
    FROZEN,
    HOST,
    ICON_PATH,
    LOG_DIR,
    MODELS_DIR,
    OPENROUTER_API_KEY,
    PORT,
)
from jarvis_core.assistant import Assistant
from jarvis_core.desktop import DesktopUIController
from jarvis_core.server import create_app, set_ui_controller

_MUTEX_HANDLE = None


def _silence_windowed_streams() -> None:
    """PyInstaller --windowed leaves stdout/stderr as None."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def setup_logging(verbose: bool = False) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter = logging.Formatter("%(asctime)s  %(levelname)-7s %(name)s  %(message)s")
    file_handler = RotatingFileHandler(
        LOG_DIR / "jarvis.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def ensure_env_file() -> None:
    """Create a first-run config file in the writable data folder."""
    if not FROZEN or CONFIG_FILE.exists():
        return
    example = BUNDLE_DIR / ".env.example"
    if not example.is_file():
        return
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(example, CONFIG_FILE)
        logging.getLogger("jarvis").warning(
            "Created configuration at %s — add your OpenRouter key there.", CONFIG_FILE
        )
    except OSError as exc:
        logging.getLogger("jarvis").warning("Could not create %s: %s", CONFIG_FILE, exc)


def diagnose() -> int:
    import importlib.metadata as metadata
    import platform

    lines = ["J.A.R.V.I.S. diagnostics", "=" * 52]
    lines.append(f"Python      : {sys.version.split()[0]} ({platform.architecture()[0]})")
    lines.append(f"Executable  : {sys.executable}")
    lines.append(f"Packaged    : {'yes' if FROZEN else 'no'}")
    lines.append(f"Config      : {CONFIG_FILE} ({'found' if CONFIG_FILE.is_file() else 'MISSING'})")
    lines.append(f"Data        : {DATA_DIR}")
    lines.append(
        f"OpenRouter  : {'key configured' if OPENROUTER_API_KEY else 'NO KEY — add OPENROUTER_API_KEY to .env'}"
    )
    try:
        from jarvis_core.config import OPENROUTER_MODEL

        lines.append(f"Model       : {OPENROUTER_MODEL}")
    except Exception:
        pass
    lines.append(
        f"Wake model  : {'found' if (MODELS_DIR / 'openwakeword' / 'hey_jarvis_v0.1.onnx').exists() else 'MISSING'}"
    )
    lines.append(f"Icon        : {'found' if ICON_PATH.is_file() else 'missing (built-in fallback)'}")
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        inputs = [d for d in devices if d["max_input_channels"] > 0]
        outputs = [d for d in devices if d["max_output_channels"] > 0]
        lines.append(f"Audio       : {len(inputs)} input / {len(outputs)} output device(s)")
        lines.append(f"Default     : in={sd.default.device[0]} out={sd.default.device[1]}")
    except Exception as exc:
        lines.append(f"Audio       : ERROR — {exc}")
    for package in (
        "openwakeword",
        "faster-whisper",
        "edge-tts",
        "onnxruntime",
        "flask",
        "pywebview",
        "pystray",
        "pyinstaller",
    ):
        try:
            lines.append(f"{package:12}: {metadata.version(package)}")
        except metadata.PackageNotFoundError:
            lines.append(f"{package:12}: not installed")
    lines.append("=" * 52)
    report = "\n".join(lines)
    print(report)
    try:
        (LOG_DIR / "diagnostics.txt").write_text(report, encoding="utf-8")
    except OSError:
        pass
    if FROZEN:
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None, report[:3500], "J.A.R.V.I.S. diagnostics", 0x40
            )
        except Exception:
            pass
    return 0


def run_ask(text: str) -> int:
    assistant = Assistant(greeting=False)
    try:
        answer = assistant._process_text(text, source="cli", speak=False)
        print(answer)
        return 0
    finally:
        assistant.shutdown()


def run_say(text: str) -> int:
    assistant = Assistant(greeting=False)
    try:
        print(f"Speaking as {assistant.settings.get('voice')} ...")
        assistant.tts.speak(
            text,
            voice=assistant.settings.get("voice", "en-GB-RyanNeural"),
            rate=assistant.settings.get("rate", "+0%"),
            volume=assistant.settings.get("volume", "+0%"),
        )
        return 0
    finally:
        assistant.shutdown()


def _single_instance(port: int) -> bool:
    """Return True when this is the only instance; reveal an existing one."""
    global _MUTEX_HANDLE
    if os.name != "nt":
        return True
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, f"Local\\JARVIS_Desktop_{port}")
    if not handle:
        return True
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        import urllib.request

        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/ui/show", method="POST"
        )
        for _ in range(10):
            try:
                urllib.request.urlopen(request, timeout=1.5).read()
                break
            except Exception:
                time.sleep(0.4)
        return False
    _MUTEX_HANDLE = handle
    return True


def run_server(
    host: str,
    port: int,
    open_browser: bool,
    window: bool,
    hotkeys: bool,
    greeting: bool = True,
    background: bool = False,
    tray: bool = False,
) -> int:
    url = f"http://{host}:{port}"
    assistant = Assistant(greeting=greeting)
    flask_app = create_app(assistant)

    native = window or background
    controller = DesktopUIController(
        assistant,
        url,
        native=native,
        hidden=background,
        tray=tray or background,
    )
    if native:
        controller.prepare()
    set_ui_controller(controller)

    assistant.start()

    if hotkeys:
        try:
            import keyboard

            def push_to_talk() -> None:
                controller.show()
                if assistant.tts.speaking:
                    assistant.tts.stop()
                assistant.audio.request_listen()

            keyboard.add_hotkey("ctrl+alt+j", push_to_talk)
            keyboard.add_hotkey("ctrl+alt+s", assistant.stop)
            logging.getLogger("jarvis").info("Global hotkeys: Ctrl+Alt+J listen, Ctrl+Alt+S stop")
        except Exception as exc:
            logging.getLogger("jarvis").warning("Global hotkeys unavailable: %s", exc)

    from werkzeug.serving import make_server

    try:
        server = make_server(host, port, flask_app, threaded=True)
    except OSError as exc:
        print(f"Could not bind {host}:{port} — {exc}")
        assistant.shutdown()
        return 1

    server_thread = threading.Thread(target=server.serve_forever, name="jarvis-http", daemon=True)
    server_thread.start()

    print()
    print("  ██  J.A.R.V.I.S.  v1.0")
    print(f"  HUD        {url}")
    print('  Wake word  "Hey Jarvis"   ·   Push-to-talk  Ctrl+Alt+J')
    print(f"  Mode       {'background + tray' if background else ('desktop window' if window else 'browser')}")
    print("  Stop       Ctrl+Alt+S     ·   Ctrl+C to exit")
    print()

    try:
        if native:
            if background and not OPENROUTER_API_KEY:
                controller.show()
            controller.run()
        else:
            if open_browser:
                threading.Thread(
                    target=lambda: (time.sleep(0.8), webbrowser.open(url)), daemon=True
                ).start()
            controller.run()
    except KeyboardInterrupt:
        print("\nShutting down J.A.R.V.I.S. ...")
    finally:
        try:
            import keyboard

            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        controller.shutdown()
        server.shutdown()
        assistant.shutdown()
    return 0


def main() -> int:
    if FROZEN:
        _silence_windowed_streams()
    try:
        if sys.stdout is not None:
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr is not None:
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="J.A.R.V.I.S. — local voice assistant")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-browser", action="store_true", help="Do not open the HUD automatically")
    parser.add_argument("--window", action="store_true", help="Open a native desktop window (pywebview)")
    parser.add_argument(
        "--background",
        action="store_true",
        help="Start hidden in the tray; say 'Hey Jarvis' to open the window",
    )
    parser.add_argument("--tray", action="store_true", help="Show a tray icon with the native window")
    parser.add_argument("--no-hotkeys", action="store_true", help="Disable global hotkeys")
    parser.add_argument("--no-greeting", action="store_true", help="Start quietly, without the spoken greeting")
    parser.add_argument("--install-autostart", action="store_true", help="Start JARVIS when you sign in")
    parser.add_argument("--uninstall-autostart", action="store_true", help="Remove the sign-in entry")
    parser.add_argument("--ask", metavar="TEXT", help="Ask one question, print the answer, and exit")
    parser.add_argument("--say", metavar="TEXT", help="Speak one line and exit")
    parser.add_argument("--diagnose", action="store_true", help="Print environment diagnostics")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)
    ensure_env_file()

    if args.diagnose:
        return diagnose()
    if args.install_autostart or args.uninstall_autostart:
        from jarvis_core import autostart

        if args.install_autostart:
            autostart.enable()
        else:
            autostart.disable()
        state = "enabled" if autostart.is_enabled() else "disabled"
        print(f"Start with Windows: {state}")
        return 0
    if args.ask:
        return run_ask(args.ask)
    if args.say:
        return run_say(args.say)

    # A packaged build behaves like an always-on assistant: start in the tray,
    # then surface the window when the wake word is heard. --window opts out.
    background = args.background or (FROZEN and not args.window and not args.no_browser)
    window = args.window or background
    open_browser = not args.no_browser and not window
    greeting = not args.no_greeting and not background

    if not _single_instance(args.port):
        return 0

    return run_server(
        args.host,
        args.port,
        open_browser,
        window,
        not args.no_hotkeys,
        greeting=greeting,
        background=background,
        tray=args.tray or background,
    )


if __name__ == "__main__":
    raise SystemExit(main())
