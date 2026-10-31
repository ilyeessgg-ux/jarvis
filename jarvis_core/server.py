"""Flask + SSE bridge between the JARVIS core and the HUD."""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any

import psutil
from flask import Flask, Response, jsonify, request, send_from_directory
from flask import stream_with_context

from .assistant import Assistant
from .config import CONFIG_FILE, DATA_DIR, SCREENSHOT_DIR, WEB_DIR

app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="/static")
app.config["JSON_SORT_KEYS"] = False

assistant: Assistant | None = None
ui_controller: Any = None
_metrics_lock = threading.Lock()
_last_net: tuple[float, int, int] | None = None
_weather_lock = threading.Lock()
_weather_cache: dict[str, Any] = {"ts": 0.0, "data": None}


def create_app(instance: Assistant) -> Flask:
    global assistant
    assistant = instance
    return app


def set_ui_controller(controller: Any) -> None:
    global ui_controller
    ui_controller = controller


def _json_event(event: dict[str, Any]) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False, default=str) + "\n\n"


@app.get("/")
def index() -> Any:
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/favicon.ico")
def favicon() -> Any:
    return Response(status=204)


@app.get("/api/events")
def events() -> Response:
    assert assistant is not None

    @stream_with_context
    def stream() -> Any:
        subscriber = assistant.bus.subscribe()
        try:
            snapshot = {"type": "snapshot", "ts": time.time(), **assistant.snapshot()}
            yield _json_event(snapshot)
            while True:
                try:
                    event = subscriber.get(timeout=15)
                    yield _json_event(event)
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            assistant.bus.unsubscribe(subscriber)

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/ask")
def ask() -> Any:
    assert assistant is not None
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    if not text:
        return jsonify({"ok": False, "error": "Text is required."}), 400
    assistant.submit_text(text, source="ui")
    return jsonify({"ok": True})


@app.post("/api/listen")
def listen() -> Any:
    assert assistant is not None
    if assistant.tts.speaking:
        assistant.tts.stop()
    if ui_controller is not None:
        ui_controller.show()
    assistant.audio.request_listen()
    return jsonify({"ok": True, "audio_available": assistant.audio.available})


@app.post("/api/ui/show")
def ui_show() -> Any:
    """Reveal the desktop window, used by a second launch of JARVIS.exe."""
    if ui_controller is None:
        return jsonify({"ok": False, "error": "Desktop UI is not available."}), 503
    ui_controller.show()
    return jsonify({"ok": True})


@app.post("/api/stop")
def stop() -> Any:
    assert assistant is not None
    assistant.stop()
    return jsonify({"ok": True})


@app.get("/api/status")
def status() -> Any:
    assert assistant is not None
    return jsonify({"ok": True, "state": assistant.state, "metrics": system_metrics()})


@app.get("/api/snapshot")
def snapshot() -> Any:
    assert assistant is not None
    return jsonify({"ok": True, **assistant.snapshot()})


@app.get("/api/history")
def history() -> Any:
    assert assistant is not None
    try:
        limit = max(1, min(int(request.args.get("limit", 40)), 200))
    except ValueError:
        limit = 40
    return jsonify({"ok": True, "history": assistant.history(limit)})


@app.post("/api/clear")
def clear() -> Any:
    assert assistant is not None
    assistant.clear_history()
    return jsonify({"ok": True})


@app.route("/api/settings", methods=["GET", "POST"])
def settings() -> Any:
    assert assistant is not None
    if request.method == "GET":
        return jsonify({"ok": True, "settings": assistant.settings})
    payload = request.get_json(silent=True) or {}
    updated = assistant.update_settings(payload)
    return jsonify({"ok": True, "settings": updated})


@app.get("/api/weather")
def weather() -> Any:
    assert assistant is not None
    with _weather_lock:
        if _weather_cache["data"] and time.time() - _weather_cache["ts"] < 600:
            return jsonify({"ok": True, **_weather_cache["data"]})
    try:
        result = assistant.toolbox.get_weather({"days": 1})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})
    if not result.get("ok"):
        return jsonify(result)
    data = {
        "location": result.get("location"),
        "current": result.get("current"),
        "forecast": (result.get("forecast") or [])[:1],
        "summary": result.get("message"),
    }
    with _weather_lock:
        _weather_cache["ts"] = time.time()
        _weather_cache["data"] = data
    return jsonify({"ok": True, **data})


@app.get("/api/screenshots/<path:name>")
def screenshot(name: str) -> Any:
    return send_from_directory(SCREENSHOT_DIR, name)


@app.post("/api/open-screenshot")
def open_screenshot() -> Any:
    assert assistant is not None
    payload = request.get_json(silent=True) or {}
    name = Path(str(payload.get("name", ""))).name
    path = SCREENSHOT_DIR / name
    if not path.exists():
        return jsonify({"ok": False, "error": "Screenshot not found."}), 404
    os.startfile(str(path))  # type: ignore[attr-defined]
    return jsonify({"ok": True})


@app.post("/api/open-data-folder")
def open_data_folder() -> Any:
    os.startfile(str(SCREENSHOT_DIR.parent))  # type: ignore[attr-defined]
    return jsonify({"ok": True})


@app.get("/api/export")
def export() -> Any:
    assert assistant is not None
    payload = assistant.memory.export_json()
    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=jarvis-memory.json"},
    )


@app.get("/api/health")
def health() -> Any:
    assert assistant is not None
    return jsonify(
        {
            "ok": True,
            "state": assistant.state,
            "llm_configured": assistant.llm.configured,
            "audio_available": assistant.audio.available,
            "stt_ready": assistant.stt.ready,
            "uptime": int(time.time() - assistant.started_at),
        }
    )


def system_metrics() -> dict[str, Any]:
    global _last_net
    with _metrics_lock:
        # A short blocking sample is reliable from Flask's per-request threads;
        # psutil's non-blocking CPU state is thread-local.
        cpu = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
        battery = psutil.sensors_battery()
        now = time.time()
        counters = psutil.net_io_counters()
        down_kbps = up_kbps = 0.0
        if _last_net:
            last_time, last_sent, last_recv = _last_net
            elapsed = max(0.1, now - last_time)
            down_kbps = max(0.0, (counters.bytes_recv - last_recv) / 1024 / elapsed)
            up_kbps = max(0.0, (counters.bytes_sent - last_sent) / 1024 / elapsed)
        _last_net = (now, counters.bytes_sent, counters.bytes_recv)
        return {
            "cpu": round(cpu, 1),
            "memory": round(memory.percent, 1),
            "memory_used_gb": round(memory.used / 1024**3, 1),
            "memory_total_gb": round(memory.total / 1024**3, 1),
            "disk": round(disk.percent, 1),
            "disk_free_gb": round(disk.free / 1024**3, 1),
            "battery": round(battery.percent, 0) if battery else None,
            "battery_plugged": bool(battery.power_plugged) if battery else None,
            "down_kbps": round(down_kbps, 1),
            "up_kbps": round(up_kbps, 1),
            "uptime": int(now - psutil.boot_time()),
            "processes": len(psutil.pids()),
        }


@app.errorhandler(404)
def not_found(_error: Any) -> Any:
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Not found."}), 404
    return send_from_directory(WEB_DIR, "index.html")


@app.errorhandler(500)
def server_error(error: Any) -> Any:
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": str(error)}), 500
    return "Internal server error", 500
