"""Ollama client (based on Nimrod's Tower's), plus model unloading for the 12 GB card."""

from __future__ import annotations

import json
import time
from typing import Any, Callable

import requests

from .config import settings
from .util import StageError


STUCK_TOKENS = 150   # this many pieces in a row of only blank space means the answer is stuck


class Ollama:
    def __init__(self, cfg: dict[str, Any] | None = None):
        self.cfg = cfg or settings()["ollama"]
        self.retries: list[str] = []   # notes about answers that needed more room
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
        solid_at, chunks = 0, 0
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
                    piece = (chunk.get("message") or {}).get("content", "")
                    text += piece
                    chunks += 1
                    if piece.strip():
                        solid_at = chunks
                    # stuck: a long run of nothing but spaces and new lines (a known local-AI habit with
                    # JSON answers). Stop now rather than waiting for it to fill the whole answer room.
                    if not chunk.get("done") and chunks - solid_at > STUCK_TOKENS:
                        on_text(text)
                        final = {"done": True, "done_reason": "stuck",
                                 "prompt_eval_count": chunk.get("prompt_eval_count")}
                        break
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
        """Ask the local AI. If the answer runs out of room, try again with more room (up to
        [ollama] max_predict / max_ctx in Settings), nudging it away from repeating itself."""
        predict = int(self.cfg["num_predict"])
        ctx = int(self.cfg["num_ctx"])
        max_predict = int(self.cfg.get("max_predict", 16384))
        max_ctx = int(self.cfg.get("max_ctx", 32768))
        penalty = float(self.cfg.get("presence_penalty", 0.0))
        stuck = 0
        for _attempt in range(4):
            payload: dict[str, Any] = {
                "model": model or self.cfg["writer_model"],
                "messages": messages,
                "stream": bool(on_text),
                "think": self.cfg.get("think", False),
                "options": {"temperature": temperature, "num_ctx": ctx, "num_predict": predict,
                            **{k: self.cfg[k] for k in ("top_p", "top_k") if k in self.cfg},
                            "presence_penalty": penalty},
            }
            if seed is not None:
                payload["options"]["seed"] = seed
            if schema is not None:
                payload["format"] = schema
            payload["stream"] = True   # always streamed, so a stuck answer can be stopped early
            data = self._stream(payload, on_text or (lambda _t: None))
            content = (data.get("message") or {}).get("content", "").strip()
            if data.get("done_reason") == "stuck":
                stuck += 1
                temperature = min(1.0, temperature + 0.15)
                penalty = min(1.5, penalty + 0.3)
                seed = (seed or 0) + 101
                self.retries.append("the AI got stuck writing blank space; trying again a little differently")
                if on_text:
                    on_text("")
                continue
            if data.get("done_reason") != "length":
                if not content:
                    raise StageError("The local AI returned an empty answer.")
                return content
            # out of room: give it more (the prompt plus a bigger answer must fit in the context)
            prompt_tokens = int(data.get("prompt_eval_count") or 0)
            if predict >= max_predict and ctx >= max_ctx:
                break
            predict = min(max_predict, predict * 2)
            ctx = min(max_ctx, max(ctx, prompt_tokens + predict + 1024))
            penalty = min(1.5, penalty + 0.3)   # long answers that run out of room are often repeating
            self.retries.append(f"answer too long; trying again with room for {predict} tokens")
            if on_text:
                on_text("")
        if stuck:
            raise StageError("The local AI kept getting stuck (it wrote only blank space). Press Run again; if it keeps "
                             "happening, try a different writer model in Settings → ollama → writer_model.")
        raise StageError("The local AI kept running out of room (it may be repeating itself). Press Run again; if it "
                         "happens again, raise [ollama] max_predict and max_ctx in Settings or make the step smaller.")

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
