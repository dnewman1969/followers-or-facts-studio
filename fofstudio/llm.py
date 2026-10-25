"""Ollama client (based on Nimrod's Tower's), plus model unloading for the 12 GB card.

Each job can use its own model (Settings → models; empty = the writer model), see JOBS.

Answers that must be JSON are checked in Python against their format (required fields, allowed values,
how many items...) and sent back to the AI up to twice with the problems listed. This matters because
some Ollama versions ignore the answer format they're given (Ollama issue #14645: with thinking off the
`format` schema is ignored on /api/chat for Qwen3 from Ollama 0.30.0, Qwen3.5/3.6 and Gemma 4). So the
first time a model is used with a format, a tiny test checks whether Ollama really enforces it; if the
chat endpoint doesn't but /api/generate does, the answers go through /api/generate instead. The result
is kept in <data>/logs/ollama-format-check.json per model and Ollama version.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

import requests

from .config import settings
from .util import StageError


STUCK_TOKENS = 150   # this many pieces in a row of only blank space means the answer is stuck
FORMAT_RETRIES = 2   # times an answer that breaks its format is sent back with the problems listed

# job -> what it does (shown in Settings → models). Empty setting = [ollama] writer_model.
JOBS = {
    "research_plan": "Plans the research agents' web searches",
    "research_quotes": "Picks the sentences to quote from sources (by number; the program copies them)",
    "research_summary": "Writes a short summary of each source",
    "stories": "Sizes up the story and writes the three story options",
    "script_plan": "Plans the script's scenes and scans the length",
    "script_write": "Writes each scene's narration",
    "storyboard": "Plans the pictures, the scene instructions and caricature designs",
    "book": "Plans and writes the book",
    "checks": "Checks done by a different model (empty = [ollama] checker_model)",
}


def model_for(job: str | None) -> str:
    cfg = settings()
    chosen = (cfg.get("models") or {}).get(job or "", "") if job else ""
    if chosen:
        return chosen
    return cfg["ollama"]["checker_model"] if job == "checks" else cfg["ollama"]["writer_model"]


def strip_fences(text: str) -> str:
    """Some models wrap JSON in ```json ... ``` fences."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def schema_problems(value: Any, schema: dict[str, Any], where: str = "the answer") -> list[str]:
    """What's wrong with an answer, checked against its JSON schema (the parts our schemas use)."""
    out: list[str] = []
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "boolean": bool}
    if kind in types and not isinstance(value, types[kind]):
        return [f"{where} should be a {kind}"]
    if kind == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
        return [f"{where} should be a whole number"]
    if kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
        return [f"{where} should be a number"]
    if "enum" in schema and value not in schema["enum"]:
        allowed = ", ".join(map(str, schema["enum"][:12])) + (" ..." if len(schema["enum"]) > 12 else "")
        out.append(f"{where} is {value!r}, which isn't allowed (allowed: {allowed})")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{where} is {value}, below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{where} is {value}, above {schema['maximum']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                out.append(f"{where} is missing \"{key}\"")
        for key, sub in (schema.get("properties") or {}).items():
            if key in value:
                out += schema_problems(value[key], sub, f'"{key}"')
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            out.append(f"{where} has {len(value)} item(s) but needs at least {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append(f"{where} has {len(value)} item(s) but may have at most {schema['maxItems']}")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                out += schema_problems(item, schema["items"], f"{where} item {i + 1}")
    return out[:20]


FORMAT_TEST_SCHEMA = {"type": "object", "properties": {"colors": {
    "type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "string", "enum": ["red", "green", "blue"]}}},
    "required": ["colors"]}
FORMAT_TEST_PROMPT = ("Reply with JSON like {\"colors\": [...]} naming exactly two colors: purple and orange. "
                      "Nothing else.")


class Ollama:
    def __init__(self, cfg: dict[str, Any] | None = None, job: str | None = None):
        self.cfg = cfg or settings()["ollama"]
        self.job = job
        self.model = model_for(job) if job else self.cfg["writer_model"]
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

    def _stream(self, payload: dict[str, Any], on_text: Callable[[str], None], path: str = "/api/chat") -> dict[str, Any]:
        """Like _post, but the answer arrives a few words at a time; on_text gets the text so far
        (about once a second) so the window can show that something is happening."""
        text, last, final = "", 0.0, {}
        solid_at, chunks = 0, 0
        with requests.Session() as s:
            s.trust_env = False
            try:
                r = s.post(self.url + path, json=payload, stream=True,
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
                    piece = (chunk.get("message") or {}).get("content", "") or chunk.get("response", "")
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
                "model": model or self.model,
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
            path = "/api/chat"
            if schema is not None and self.cfg.get("format_check", True) and \
                    self.format_route(payload["model"]) == "generate":
                payload, path = _as_generate(payload), "/api/generate"
            data = self._stream(payload, on_text or (lambda _t: None), path)
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
                  model: str | None = None, lenient: bool = False, **kw: Any) -> Any:
        """A JSON answer checked against its format. One that breaks it goes back to the AI with the
        problems listed (up to FORMAT_RETRIES times). lenient=True returns the last answer anyway if it's
        still off (for callers that repair it themselves); otherwise that's a StageError."""
        msgs = list(messages)
        problems: list[str] = []
        value: Any = None
        for attempt in range(FORMAT_RETRIES + 1):
            text = self.chat(msgs, model=model, schema=schema, **kw)
            try:
                value = json.loads(strip_fences(text))
                problems = schema_problems(value, schema)
            except json.JSONDecodeError as exc:
                value, problems = None, [f"it isn't valid JSON ({exc})"]
            if not problems:
                return value
            self.retries.append(f"answer broke its format ({problems[0]}); asking again")
            if attempt < FORMAT_RETRIES:
                msgs = list(messages) + [
                    {"role": "assistant", "content": text[:6000]},
                    {"role": "user", "content": "Your answer doesn't follow the required JSON format: "
                                                + "; ".join(problems[:8]) + ". Answer again with the whole JSON, "
                                                "fixed, and nothing else."}]
        if lenient and value is not None:
            return value
        name = model or self.model
        raise StageError(f"The local AI ({name}) kept answering in the wrong format: {'; '.join(problems[:3])}. "
                         "Press Run again. If it keeps happening, update Ollama (some versions ignore the answer "
                         "format; see Queue → GPU check) or pick another model in Settings → models.")

    # ------------------------------------------------------------ does Ollama obey the format?
    def version(self) -> str:
        try:
            with requests.Session() as s:
                s.trust_env = False
                return str(s.get(self.url + "/api/version", timeout=4).json().get("version", "unknown"))
        except Exception:  # noqa: BLE001 - an old or fake server: just "unknown"
            return "unknown"

    def format_route(self, model: str) -> str:
        """'chat' if Ollama's chat endpoint enforces answer formats for this model, 'generate' if only the
        generate endpoint does, 'none' if neither (then only our own checks catch problems)."""
        key = f"{model}@{self.version()}"
        if key in _ROUTES:
            return _ROUTES[key]
        saved = _load_routes()
        if key in saved:
            _ROUTES[key] = saved[key]["route"]
            return _ROUTES[key]
        result = self.format_test(model)
        _ROUTES[key] = result["route"]
        saved[key] = result
        _save_routes(saved)
        return result["route"]

    def format_test(self, model: str) -> dict[str, Any]:
        """Ask for 2 colors while the format demands exactly 4 from red/green/blue: an Ollama that enforces
        formats returns 4 allowed colors anyway."""
        out: dict[str, Any] = {"model": model, "ollama": self.version(), "tested_at": time.strftime("%Y-%m-%d %H:%M")}
        base = {"model": model, "messages": [{"role": "user", "content": FORMAT_TEST_PROMPT}],
                "think": self.cfg.get("think", False), "format": FORMAT_TEST_SCHEMA, "stream": True,
                "options": {"temperature": 0, "num_predict": 200, "num_ctx": 2048}}
        for name, payload, path in (("chat", base, "/api/chat"), ("generate", _as_generate(base), "/api/generate")):
            try:
                text = self._stream(payload, lambda _t: None, path)["message"]["content"]
                ok = not schema_problems(json.loads(strip_fences(text)), FORMAT_TEST_SCHEMA)
            except (json.JSONDecodeError, StageError, requests.RequestException, KeyError, TypeError):
                ok = False
            out[name] = ok
            if ok:
                out["route"] = name
                return out
        out["route"] = "none"
        return out

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


_ROUTES: dict[str, str] = {}


def _routes_file():
    from .config import data_dir
    return data_dir() / "logs" / "ollama-format-check.json"


def _load_routes() -> dict[str, Any]:
    try:
        return json.loads(_routes_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_routes(data: dict[str, Any]) -> None:
    try:
        f = _routes_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass


def forget_format_checks() -> None:
    """Test again next time (after updating Ollama or changing models)."""
    _ROUTES.clear()
    _save_routes({})


def _as_generate(payload: dict[str, Any]) -> dict[str, Any]:
    """The same request for /api/generate: one prompt instead of a conversation."""
    msgs = payload["messages"]
    system = "\n\n".join(m["content"] for m in msgs if m["role"] == "system")
    rest = [m for m in msgs if m["role"] != "system"]
    if len(rest) == 1:
        prompt = rest[0]["content"]
    else:
        prompt = "\n\n".join(("Your earlier answer:\n" if m["role"] == "assistant" else "") + m["content"]
                              for m in rest)
    out = {k: v for k, v in payload.items() if k != "messages"}
    out["prompt"] = prompt
    if system:
        out["system"] = system
    return out
