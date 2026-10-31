"""Desktop shell: hidden native window, tray icon, wake-to-open behaviour."""

from __future__ import annotations

import ctypes
import logging
import os
import queue
import threading
import webbrowser
from typing import Any

from . import autostart
from .assistant import Assistant
from .config import CONFIG_FILE, DATA_DIR, ICON_PATH, WEBVIEW_DIR
from .tray import TrayIcon

log = logging.getLogger("jarvis.desktop")

WINDOW_TITLE = "J.A.R.V.I.S."


def bring_to_front(title: str = WINDOW_TITLE) -> None:
    """Nudge a window to the foreground on Windows."""
    if os.name != "nt":
        return
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


class DesktopUIController:
    def __init__(
        self,
        assistant: Assistant,
        url: str,
        *,
        native: bool,
        hidden: bool = False,
        tray: bool = False,
    ) -> None:
        self.assistant = assistant
        self.url = url
        self.native = native
        self.hidden = hidden
        self.use_tray = tray
        self.window: Any = None
        self.tray: TrayIcon | None = None
        self._quitting = False
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._show_when_ready = False
        self._browser_opened = False

    # ------------------------------------------------------------------ setup
    def prepare(self) -> None:
        """Create the window object. The GUI loop starts in run()."""
        if not self.native:
            return
        try:
            import webview

            WEBVIEW_DIR.mkdir(parents=True, exist_ok=True)
            self.window = webview.create_window(
                WINDOW_TITLE,
                self.url,
                width=1500,
                height=940,
                min_size=(1100, 700),
                hidden=self.hidden,
                background_color="#02060a",
            )
            self.window.events.closing += self._on_closing
            self.window.events.closed += self._on_closed
        except Exception as exc:
            log.warning("Native window unavailable: %s", exc)
            self.native = False
            self.window = None

    def run(self) -> None:
        """Block on the GUI loop (or the background loop for browser-only mode)."""
        self._start_watchdog()
        if self.use_tray:
            self._start_tray()

        if self.window is not None:
            import webview

            kwargs: dict[str, Any] = {
                "private_mode": False,
                "storage_path": str(WEBVIEW_DIR),
            }
            if ICON_PATH.is_file():
                kwargs["icon"] = str(ICON_PATH)
            try:
                webview.start(self._on_gui_ready, **kwargs)
                return
            except Exception as exc:
                log.exception("Native window failed to start, falling back to browser: %s", exc)
                self.native = False
                self.window = None
                webbrowser.open(self.url)

        try:
            while not self._stop.wait(0.5):
                pass
        except KeyboardInterrupt:
            pass

    def _on_gui_ready(self) -> None:
        self._ready.set()
        if self._show_when_ready:
            self._show_when_ready = False
            self.show()

    def _start_watchdog(self) -> None:
        threading.Thread(target=self._watch_events, name="jarvis-ui-wake", daemon=True).start()

    def _watch_events(self) -> None:
        subscriber = self.assistant.bus.subscribe()
        try:
            while not self._stop.is_set():
                try:
                    event = subscriber.get(timeout=0.4)
                except queue.Empty:
                    continue
                if event.get("type") == "wake":
                    self.show()
        finally:
            self.assistant.bus.unsubscribe(subscriber)

    def _start_tray(self) -> None:
        try:
            self.tray = TrayIcon(
                on_open=self.show,
                on_listen=self.listen,
                on_quit=self.quit,
                on_open_data=self.open_data_folder,
                on_open_config=self.open_config_file,
                wake_enabled=lambda: bool(self.assistant.settings.get("wake_enabled", True)),
                on_toggle_wake=self.toggle_wake,
                on_toggle_autostart=autostart.toggle,
                autostart_enabled=autostart.is_enabled,
            )
            self.tray.start()
            threading.Timer(
                1.5,
                lambda: self.tray
                and self.tray.notify('Running in the background. Say "Hey Jarvis" or use this icon.'),
            ).start()
        except Exception as exc:
            log.warning("Tray icon unavailable: %s", exc)
            self.tray = None

    # ------------------------------------------------------------------ window
    def show(self) -> None:
        if self._stop.is_set():
            return
        if self.window is None:
            if not self._browser_opened:
                self._browser_opened = True
                webbrowser.open(self.url)
            return
        if not self._ready.wait(6.0):
            self._show_when_ready = True
            return
        try:
            self.window.show()
            try:
                self.window.restore()
            except Exception:
                pass
            threading.Timer(0.25, bring_to_front).start()
        except Exception as exc:
            log.warning("Could not show window: %s", exc)

    def hide(self) -> None:
        if self.window is not None:
            try:
                self.window.hide()
            except Exception:
                pass

    def listen(self) -> None:
        self.show()
        try:
            if self.assistant.tts.speaking:
                self.assistant.tts.stop()
            self.assistant.audio.request_listen()
        except Exception:
            log.exception("Could not start listening")

    def toggle_wake(self) -> bool:
        enabled = not bool(self.assistant.settings.get("wake_enabled", True))
        self.assistant.update_settings({"wake_enabled": enabled})
        return enabled

    def open_data_folder(self) -> None:
        try:
            os.startfile(str(DATA_DIR))  # type: ignore[attr-defined]
        except Exception:
            log.exception("Could not open data folder")

    def open_config_file(self) -> None:
        target = CONFIG_FILE if CONFIG_FILE.is_file() else DATA_DIR
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
        except Exception:
            log.exception("Could not open configuration file")

    def _on_closing(self) -> bool:
        if self._quitting or not self.use_tray:
            return True
        # Background mode: the window lives in the tray, so closing hides it.
        self.hide()
        return False

    def _on_closed(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------ quit
    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self._stop.set()
        if self.tray:
            self.tray.stop()
            self.tray = None
        try:
            self.assistant.stop()
        except Exception:
            pass
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
        else:
            # Nothing blocks; run() will return from its wait loop.
            pass

    def shutdown(self) -> None:
        self._stop.set()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
            self.tray = None
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
            self.window = None
