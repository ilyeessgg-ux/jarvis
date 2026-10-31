"""System tray icon for J.A.R.V.I.S. background mode."""

from __future__ import annotations

import logging
import threading
from typing import Callable

import pystray
from PIL import Image, ImageDraw

from .config import ICON_PATH

log = logging.getLogger("jarvis.tray")


def _fallback_icon(size: int = 64) -> Image.Image:
    """Draw a small arc-reactor badge when the .ico asset is unavailable."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = max(1, size // 32)
    draw.ellipse(
        (margin, margin, size - margin - 1, size - margin - 1),
        fill=(3, 12, 18, 255),
        outline=(112, 236, 255, 255),
        width=max(1, size // 24),
    )
    inset = size * 0.22
    draw.ellipse(
        (inset, inset, size - inset, size - inset),
        outline=(255, 199, 107, 235),
        width=max(1, size // 32),
    )
    core = size * 0.36
    draw.ellipse(
        (core, core, size - core, size - core),
        fill=(142, 243, 255, 255),
        outline=(220, 255, 255, 255),
        width=max(1, size // 48),
    )
    return image


def load_icon() -> Image.Image:
    if ICON_PATH.is_file():
        try:
            with Image.open(ICON_PATH) as image:
                return image.convert("RGBA")
        except Exception as exc:
            log.warning("Could not load tray icon: %s", exc)
    return _fallback_icon()


class TrayIcon:
    """Runs a pystray icon on its own thread.

    All callbacks run on pystray's thread, so the callers must be thread-safe
    (the desktop window controller dispatches to pywebview's UI thread).
    """

    def __init__(
        self,
        *,
        on_open: Callable[[], None],
        on_listen: Callable[[], None],
        on_quit: Callable[[], None],
        on_open_data: Callable[[], None],
        on_open_config: Callable[[], None],
        wake_enabled: Callable[[], bool],
        on_toggle_wake: Callable[[], bool],
        on_toggle_autostart: Callable[[], bool],
        autostart_enabled: Callable[[], bool],
    ) -> None:
        self._on_open = on_open
        self._on_listen = on_listen
        self._on_quit = on_quit
        self._on_open_data = on_open_data
        self._on_open_config = on_open_config
        self._wake_enabled = wake_enabled
        self._on_toggle_wake = on_toggle_wake
        self._on_toggle_autostart = on_toggle_autostart
        self._autostart_enabled = autostart_enabled
        self._thread: threading.Thread | None = None
        self._icon = pystray.Icon(
            "jarvis",
            load_icon(),
            'J.A.R.V.I.S. — listening for "Hey Jarvis"',
            menu=self._menu(),
        )

    def _menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("Open J.A.R.V.I.S.", self._open, default=True),
            pystray.MenuItem("Listen now", self._listen),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Wake word",
                self._toggle_wake,
                checked=lambda _item: bool(self._wake_enabled()),
            ),
            pystray.MenuItem(
                "Start with Windows",
                self._toggle_autostart,
                checked=lambda _item: bool(self._autostart_enabled()),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Edit settings (.env)", self._open_config),
            pystray.MenuItem("Open data folder", self._open_data),
            pystray.MenuItem("Quit J.A.R.V.I.S.", self._quit),
        )

    def _open(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self._on_open()

    def _listen(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self._on_listen()

    def _toggle_wake(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        try:
            self._on_toggle_wake()
            self._icon.update_menu()
        except Exception:
            log.exception("Could not toggle wake word")

    def _toggle_autostart(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        try:
            self._on_toggle_autostart()
            self._icon.update_menu()
        except Exception:
            log.exception("Could not toggle autostart")

    def _open_data(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self._on_open_data()

    def _open_config(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self._on_open_config()

    def _quit(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self._on_quit()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._icon.run, name="jarvis-tray", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=2.0)

    def notify(self, message: str, title: str = "J.A.R.V.I.S.") -> None:
        try:
            self._icon.notify(message, title)
        except Exception:
            pass
