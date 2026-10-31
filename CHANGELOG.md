# Changelog

## 1.0.0 — 2026-10-31

First public release.

### Included

- Always-on **“Hey Jarvis”** wake word with local openWakeWord detection.
- Local faster-whisper speech recognition and edge-tts British voice.
- Streaming OpenRouter chat with tool calling, persistent SQLite memory,
  reminders, notes, and conversation history.
- Holographic HUD with reactor, waveform, telemetry, settings, and screenshot
  lightbox.
- Background/tray mode: the window opens on wake and hides on close.
- Single-instance handling, wake-word toggle, start-with-Windows toggle, and
  tray shortcuts to listen, edit settings, open the data folder, and quit.
- Portable Windows x64 build (`JARVIS.exe`, one-folder) and CI release workflow.

### Notes

- Windows 10/11 x64 is required for PC-control tools.
- Reasonings and neural speech require internet access and an OpenRouter key.
