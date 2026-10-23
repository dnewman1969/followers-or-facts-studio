"""Ollama client (based on Nimrod's Tower's), plus model unloading for the 12 GB card."""

from __future__ import annotations

import json
import time
from typing import Any, Callable

import requests

from .config import settings
from .util import StageError


class Ollama:
    def __init__(self, cfg: dict[str, Any] | None = None):
        self.cfg = cfg or settings()["ollama"]
        self.url = self.cfg["url"].rstrip("/")

    def _post(self, path: str, payload: dict[str, Any], timeout: float | tuple) -> dict[str, Any]:
        with requests.Session() as s:
            s.trust_env = False  # never send local traffic through a proxy
            try:
                r = s.post(self.url + path, json=payload, timeout=timeout, allow_redirects=False)
            except requests.ConnectionError:
                raise StageError(f"Ollama is not running at {self.url}. Start Ollama and try again.")
            if r.status_code == 404 and "model" in r.text:
                raise StageError(f"Ollama doesn't have model {payload.get('model')!r}. "
                                 f"Run: ollama pull {payload.get('model')}")
            r.raise_for_status()
            data = r.json()
        if data.get("error"):
            raise StageError(f"Ollama error: {data['error']}")
        return data

    def health(self) -> tuple[bool, str]:
        try:
            with requests.Session() as s:
                s.trust_env = False
                r = s.get(self.url + "/api/tags", timeout=4)
                r.raise_for_status()
                names = [m["name"] for m in r.json().get("models", [])]
            return True, f"Ollama online, {len(names)} models: {', '.join(names[:8])}"
        except Exception as exc:  # noqa: BLE001 - shown to the user
            return False, f"Ollama not reachable at {self.url}: {exc}"

    def _stream(self, payload: dict[str, Any], on_text: Callable[[str], None]) -> dict[str, Any]:
        """Like _post, but the answer arrives a few words at a time; on_text gets the text so far
        (about once a second) so the window can show that something is happening."""
        text, last, final = "", 0.0, {}
        with requests.Session() as s:
            s.trust_env = False
            try:
                r = s.post(self.url + "/api/chat", json=payload, stream=True,
                           timeout=(5, self.cfg["timeout_seconds"]), allow_redirects=False)
            except requests.ConnectionError:
                raise StageError(f"Ollama is not running at {self.url}. Start Ollama and try again.")
            with r:
                if r.status_code == 404 and "model" in r.text:
                    raise StageError(f"Ollama doesn't have model {payload.get('model')!r}. "
                                     f"Run: ollama pull {payload.get('model')}")
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise StageError(f"Ollama error: {chunk['error']}")
                    text += (chunk.get("message") or {}).get("content", "")
                    if time.monotonic() - last > 1.0:
                        last = time.monotonic()
                        on_text(text)
                    if chunk.get("done"):
                        final = chunk
                        break
        final["message"] = {"content": text}
        return final

    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             schema: dict[str, Any] | None = None, temperature: float = 0.4,
             seed: int | None = None, on_text: Callable[[str], None] | None = None) -> str:
        payload: dict[str, Any] = {
            "model": model or self.cfg["writer_model"],
            "messages": messages,
            "stream": bool(on_text),
            "think": self.cfg.get("think", False),
            "options": {"temperature": temperature, "num_ctx": self.cfg["num_ctx"],
                        "num_predict": self.cfg["num_predict"],
                        **{k: self.cfg[k] for k in ("top_p", "top_k", "presence_penalty") if k in self.cfg}},
        }
        if seed is not None:
            payload["options"]["seed"] = seed
        if schema is not None:
            payload["format"] = schema
        if on_text:
            data = self._stream(payload, on_text)
        else:
            data = self._post("/api/chat", payload, timeout=(5, self.cfg["timeout_seconds"]))
        content = (data.get("message") or {}).get("content", "").strip()
        if not content:
            raise StageError("The local AI returned an empty answer.")
        if data.get("done_reason") == "length":
            raise StageError("The local AI ran out of room before finishing. Raise "
                             "[ollama] num_predict in Settings or pick fewer claims.")
        return content

    def chat_json(self, messages: list[dict[str, str]], schema: dict[str, Any],
                  model: str | None = None, **kw: Any) -> Any:
        text = self.chat(messages, model=model, schema=schema, **kw)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise StageError(f"The local AI returned broken JSON ({exc}). Run the stage again.")

    def unload_all(self) -> list[str]:
        """Free the GPU before ComfyUI or ffmpeg needs it (keep_alive: 0)."""
        unloaded = []
        try:
            with requests.Session() as s:
                s.trust_env = False
                running = s.get(self.url + "/api/ps", timeout=4).json().get("models", [])
                for m in running:
                    s.post(self.url + "/api/generate", json={"model": m["name"], "keep_alive": 0},
                           timeout=30)
                    unloaded.append(m["name"])
        except Exception:  # noqa: BLE001 - Ollama not running means nothing to unload
            pass
        return unloaded
