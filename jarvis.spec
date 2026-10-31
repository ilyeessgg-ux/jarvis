# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition for the J.A.R.V.I.S. desktop app."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs, copy_metadata

ROOT = Path(SPECPATH)
required = [
    ROOT / "models" / "openwakeword" / "hey_jarvis_v0.1.onnx",
    ROOT / "models" / "whisper" / "base.en" / "model.bin",
    ROOT / "web" / "index.html",
    ROOT / "assets" / "jarvis.ico",
]
missing = [str(item) for item in required if not item.exists()]
if missing:
    raise SystemExit(
        "Build prerequisites missing:\n  "
        + "\n  ".join(missing)
        + "\nRun: runtime\\python.exe download_models.py"
    )

datas = [
    (str(ROOT / "web"), "web"),
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / "models" / "openwakeword"), "models/openwakeword"),
    (str(ROOT / "models" / "whisper" / "base.en"), "models/whisper/base.en"),
    (str(ROOT / ".env.example"), "."),
    (str(ROOT / "LICENSE"), "."),
]
binaries = []
hiddenimports = [
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "pystray._win32",
    "pycaw",
    "pycaw.pycaw",
    "comtypes.gen",
    "keyboard",
    "pyperclip",
    "ddgs",
    "dateparser",
    "feedparser",
]

# Packages that load native DLLs or generated modules at runtime need to be
# collected explicitly. Keep the list narrow so the bundle stays manageable.
for package in (
    "openwakeword",
    "faster_whisper",
    "ctranslate2",
    "av",
    "onnxruntime",
    "edge_tts",
    "webview",
    "pystray",
    "comtypes",
    "pycaw",
    "sounddevice",
    "soundfile",
    "imageio_ffmpeg",
    "ddgs",
    "dateparser",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

for distribution in ("pywebview", "pystray", "faster-whisper", "ctranslate2", "openwakeword"):
    try:
        datas += copy_metadata(distribution)
    except Exception:
        pass

# PyAV and ctranslate2 ship DLLs that PyInstaller sometimes misses.
binaries += collect_dynamic_libs("av")
binaries += collect_dynamic_libs("ctranslate2")

excludes = [
    "tkinter",
    "matplotlib",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "IPython",
    "notebook",
    "pytest",
]

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="JARVIS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "jarvis.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="JARVIS",
)
