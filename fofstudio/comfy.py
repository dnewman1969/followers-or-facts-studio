"""ComfyUI client: fill a saved workflow template, queue it, wait, download results.

Workflow templates are ComfyUI "API format" JSON files (in ComfyUI: Settings ->
enable Dev mode -> Workflow menu -> Export (API)). Any string value that is
exactly a placeholder such as "{{PROMPT}}" is replaced; "{{SEED}}", "{{WIDTH}}"
and the other number placeholders become real numbers. See comfy_workflows/README.md.
"""

from __future__ import annotations

import copy
import json
import random
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import requests

from .config import repo_path, settings
from .util import StageError

NUMERIC = {"SEED", "WIDTH", "HEIGHT", "FRAMES", "FPS", "STEPS", "SECONDS"}


def fill(template: Any, values: dict[str, Any]) -> Any:
    """Replace "{{NAME}}" placeholders anywhere in the workflow."""
    if isinstance(template, dict):
        return {k: fill(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [fill(v, values) for v in template]
    if isinstance(template, str) and template.startswith("{{") and template.endswith("}}"):
        name = template[2:-2].strip()
        if name not in values:
            raise StageError(f"Workflow placeholder {{{{{name}}}}} has no value.")
        value = values[name]
        return int(value) if name in NUMERIC else value
    if isinstance(template, str) and "{{" in template:
        for name, value in values.items():
            template = template.replace("{{" + name + "}}", str(value))
    return template


def placeholders(template: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(template, dict):
        for v in template.values():
            found |= placeholders(v)
    elif isinstance(template, list):
        for v in template:
            found |= placeholders(v)
    elif isinstance(template, str):
        import re
        found |= set(re.findall(r"\{\{\s*([A-Z_]+)\s*\}\}", template))
    return found


def load_workflow(setting_key: str) -> tuple[dict[str, Any], Path]:
    path = repo_path(settings()["comfyui"][setting_key])
    if not path.exists():
        raise StageError(f"ComfyUI workflow file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("_about", None)
    return data, path


class Comfy:
    def __init__(self, url: str | None = None):
        self.url = (url or settings()["comfyui"]["url"]).rstrip("/")
        self.client_id = uuid.uuid4().hex

    def _session(self) -> requests.Session:
        s = requests.Session()
        s.trust_env = False
        return s

    def health(self) -> tuple[bool, str]:
        try:
            with self._session() as s:
                info = s.get(self.url + "/system_stats", timeout=4).json()
            devices = info.get("devices", [])
            gpu = devices[0]["name"] if devices else "no GPU reported"
            return True, f"ComfyUI online ({gpu})"
        except Exception as exc:  # noqa: BLE001
            return False, f"ComfyUI not reachable at {self.url}: {exc}"

    def upload_image(self, path: Path) -> str:
        with self._session() as s, open(path, "rb") as fh:
            r = s.post(self.url + "/upload/image",
                       files={"image": (Path(path).name, fh, "image/png")},
                       data={"overwrite": "true", "type": "input"}, timeout=120)
            r.raise_for_status()
            info = r.json()
        sub = info.get("subfolder") or ""
        return f"{sub}/{info['name']}" if sub else info["name"]

    def free_memory(self) -> None:
        try:
            with self._session() as s:
                s.post(self.url + "/free", json={"unload_models": True, "free_memory": True},
                       timeout=30)
        except Exception:  # noqa: BLE001
            pass

    def run(self, workflow: dict[str, Any], timeout: float | None = None,
            on_progress: Callable[[str], None] | None = None,
            cancelled: Callable[[], bool] | None = None) -> list[dict[str, Any]]:
        """Queue a workflow and return its output files as {filename, subfolder, type, kind}."""
        timeout = timeout or settings()["comfyui"]["timeout_seconds"]
        with self._session() as s:
            try:
                r = s.post(self.url + "/prompt",
                           json={"prompt": workflow, "client_id": self.client_id}, timeout=30)
            except requests.ConnectionError:
                raise StageError(f"ComfyUI is not running at {self.url}. Start ComfyUI and try again.")
            if r.status_code != 200:
                raise StageError(f"ComfyUI rejected the workflow: {self._explain(r)}")
            prompt_id = r.json()["prompt_id"]
            start = time.time()
            while True:
                if cancelled and cancelled():
                    s.post(self.url + "/interrupt", timeout=10)
                    raise StageError("Cancelled.")
                if time.time() - start > timeout:
                    s.post(self.url + "/interrupt", timeout=10)
                    raise StageError(f"ComfyUI took longer than {timeout:.0f} s.")
                hist = s.get(f"{self.url}/history/{prompt_id}", timeout=30).json()
                if prompt_id in hist:
                    entry = hist[prompt_id]
                    status = entry.get("status", {})
                    if status.get("status_str") == "error":
                        msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                        detail = msgs[0][1].get("exception_message", "") if msgs else ""
                        raise StageError(f"ComfyUI failed: {detail.strip() or 'see the ComfyUI window'}")
                    return self._outputs(entry)
                if on_progress:
                    on_progress(f"ComfyUI working... {time.time() - start:.0f} s")
                time.sleep(2)

    @staticmethod
    def _explain(r: requests.Response) -> str:
        try:
            data = r.json()
        except ValueError:
            return r.text[:500]
        err = data.get("error", {})
        parts = [err.get("message", "")]
        for node_id, node in (data.get("node_errors") or {}).items():
            for e in node.get("errors", []):
                parts.append(f"node {node_id} ({node.get('class_type')}): {e.get('message')} "
                             f"{e.get('details', '')}")
        text = "; ".join(p for p in parts if p)
        if "not in list" in text or "value_not_in_list" in text:
            text += (" -- a model file named in the workflow isn't in your ComfyUI models "
                     "folder. Check the names in docs/MODELS.md.")
        return text

    @staticmethod
    def _outputs(entry: dict[str, Any]) -> list[dict[str, Any]]:
        files = []
        for node_out in entry.get("outputs", {}).values():
            for kind in ("images", "gifs", "videos", "audio"):
                for f in node_out.get(kind, []) or []:
                    if isinstance(f, dict) and f.get("filename"):
                        files.append({**f, "kind": kind})
        if not files:
            raise StageError("ComfyUI finished but produced no output file. Does the workflow "
                             "end in a Save node?")
        return files

    def download(self, file: dict[str, Any], dest: Path) -> Path:
        params = {"filename": file["filename"], "subfolder": file.get("subfolder", ""),
                  "type": file.get("type", "output")}
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self._session() as s:
            r = s.get(self.url + "/view", params=params, timeout=300, stream=True)
            r.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
        return dest


def new_seed() -> int:
    return random.randint(1, 2**31 - 1)


def run_template(setting_key: str, values: dict[str, Any], dest_stem: Path,
                 on_progress=None, cancelled=None) -> tuple[list[Path], dict[str, Any]]:
    template, path = load_workflow(setting_key)
    workflow = fill(copy.deepcopy(template), values)
    client = Comfy()
    files = client.run(workflow, on_progress=on_progress, cancelled=cancelled)
    saved = []
    for n, f in enumerate(files):
        suffix = Path(f["filename"]).suffix
        dest = Path(f"{dest_stem}{'' if n == 0 else f'-{n}'}{suffix}")
        saved.append(client.download(f, dest))
    return saved, {"workflow": path.name}
