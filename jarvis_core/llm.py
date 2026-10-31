"""Streaming OpenRouter chat client with OpenAI-compatible tool calling."""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable

import requests


class OpenRouterError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, api_key: str, base_url: str, default_model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://127.0.0.1:7777",
                "X-Title": "JARVIS",
            }
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        on_text: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise OpenRouterError("No OpenRouter API key is configured. Add OPENROUTER_API_KEY to jarvis/.env.")

        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": True,
            "temperature": 0.65,
            "max_tokens": 1200,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        last_error: Exception | None = None
        for attempt in range(2):
            if cancel_event and cancel_event.is_set():
                return {"content": "", "tool_calls": [], "finish_reason": "cancelled"}
            try:
                return self._stream_once(payload, on_text, cancel_event)
            except OpenRouterError as exc:
                last_error = exc
                # Retry transient failures once, but never after partial speech.
                message = str(exc).lower()
                transient = any(token in message for token in ("429", "500", "502", "503", "504", "timeout", "temporar"))
                if attempt == 0 and transient:
                    time.sleep(1.2)
                    continue
                raise
            except requests.RequestException as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(1.2)
                    continue
                raise OpenRouterError(f"Network error contacting OpenRouter: {exc}") from exc
        raise OpenRouterError(str(last_error or "OpenRouter request failed."))

    def _stream_once(
        self,
        payload: dict[str, Any],
        on_text: Callable[[str], None] | None,
        cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        response = self._session.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            stream=True,
            timeout=(20, 300),
        )
        if response.status_code != 200:
            detail = response.text[:800]
            try:
                parsed = response.json()
                detail = parsed.get("error", {}).get("message", detail)
            except Exception:
                pass
            response.close()
            raise OpenRouterError(f"OpenRouter HTTP {response.status_code}: {detail}")

        content_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        finish_reason = None
        usage: dict[str, Any] = {}

        try:
            for raw_line in response.iter_lines(decode_unicode=True):
                if cancel_event and cancel_event.is_set():
                    finish_reason = "cancelled"
                    break
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if chunk.get("error"):
                    raise OpenRouterError(str(chunk["error"].get("message", chunk["error"])))
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                finish_reason = choice.get("finish_reason") or finish_reason
                delta = choice.get("delta") or {}
                text = delta.get("content")
                if text:
                    content_parts.append(text)
                    if on_text:
                        on_text(text)
                for partial in delta.get("tool_calls") or []:
                    index = int(partial.get("index", 0))
                    entry = tool_calls.setdefault(
                        index,
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    if partial.get("id"):
                        entry["id"] = partial["id"]
                    function = partial.get("function") or {}
                    if function.get("name"):
                        entry["function"]["name"] = function["name"]
                    if function.get("arguments"):
                        entry["function"]["arguments"] += function["arguments"]
        finally:
            response.close()

        assembled = []
        for index in sorted(tool_calls):
            entry = tool_calls[index]
            if not entry["id"]:
                entry["id"] = f"call_{index}_{int(time.time())}"
            assembled.append(entry)
        return {
            "content": "".join(content_parts).strip(),
            "tool_calls": assembled,
            "finish_reason": finish_reason,
            "usage": usage,
        }
