"""Start-with-Windows integration (HKCU Run key)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .config import APP_DIR, FROZEN

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "JARVIS"


def _command() -> str:
    if FROZEN:
        executable = Path(sys.executable).resolve()
        return f'"{executable}" --background'

    executable = Path(sys.executable).resolve()
    console_free = executable.with_name("pythonw.exe")
    if console_free.is_file():
        executable = console_free
    return f'"{executable}" "{APP_DIR / "app.py"}" --background'


def is_enabled() -> bool:
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
    except OSError:
        return False
    return bool(value)


def enable() -> None:
    if os.name != "nt":
        return
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())


def disable() -> None:
    if os.name != "nt":
        return
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except OSError:
        pass


def toggle() -> bool:
    """Flip the setting and return the new enabled state."""
    if is_enabled():
        disable()
        return False
    enable()
    return True
