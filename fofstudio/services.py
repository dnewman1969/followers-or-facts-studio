"""Start Ollama and ComfyUI if they aren't running, so one desktop icon does everything.

ComfyUI is found automatically. These layouts are recognised, in this order:
  1. [services] comfyui_command in Settings (anything you type there wins)
  2. a ComfyUI folder with main.py (git install), using its own venv / .venv,
     the portable build's python_embeded, or Python 3.11/3.12 from the py launcher
  3. the portable build's run_nvidia_gpu.bat
  4. the ComfyUI Desktop app (it runs its own server, usually on port 8000)

ComfyUI started by us runs without a console window; its output goes to
<data>/logs/comfyui.log. Ollama is started the normal way (its tray app).
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .config import Paths, save_settings, settings
from .util import read_json, write_json

CREATE_NO_WINDOW = 0x08000000
DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def _get(url: str, timeout: float = 2.0) -> bool:
    try:
        with requests.Session() as s:
            s.trust_env = False
            return s.get(url, timeout=timeout).status_code == 200
    except requests.RequestException:
        return False


# ---------------------------------------------------------------- Ollama
def ollama_up() -> bool:
    return _get(settings()["ollama"]["url"].rstrip("/") + "/api/tags")


def find_ollama() -> list[str] | None:
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama"
    app = local / "ollama app.exe"
    if app.exists():
        return [str(app)]
    exe = shutil.which("ollama") or (str(local / "ollama.exe") if (local / "ollama.exe").exists() else None)
    return [exe, "serve"] if exe else None


def start_ollama() -> str:
    cmd = find_ollama()
    if not cmd:
        return "Ollama isn't installed (looked in %LOCALAPPDATA%\\Programs\\Ollama and PATH)."
    _spawn(cmd, Path(cmd[0]).parent, Paths().ensure().logs / "ollama.log")
    return "Starting Ollama..."


# ---------------------------------------------------------------- ComfyUI
def comfy_candidates() -> list[str]:
    """URLs to try: the configured one, then ComfyUI's two usual ports."""
    url = settings()["comfyui"]["url"].rstrip("/")
    found = [url]
    for port in (8188, 8000):
        alt = f"http://127.0.0.1:{port}"
        if alt not in found:
            found.append(alt)
    return found


def comfy_url_up() -> str | None:
    for url in comfy_candidates():
        if _get(url + "/system_stats"):
            return url
    return None


def remember_comfy_url(url: str) -> None:
    s = settings()
    if s["comfyui"]["url"].rstrip("/") != url:
        s["comfyui"]["url"] = url
        save_settings(s)


def _python_for(folder: Path) -> list[str] | None:
    for cand in (folder / "venv" / "Scripts" / "python.exe", folder / ".venv" / "Scripts" / "python.exe",
                 folder.parent / "python_embeded" / "python.exe", folder / "python_embeded" / "python.exe",
                 folder / "venv" / "bin" / "python", folder / ".venv" / "bin" / "python"):
        if cand.exists():
            return [str(cand)]
    if os.name == "nt" and shutil.which("py"):
        for ver in ("-3.11", "-3.12"):
            try:
                subprocess.run(["py", ver, "-c", "import torch"], capture_output=True, timeout=60,
                               check=True, creationflags=CREATE_NO_WINDOW)
                return ["py", ver]
            except Exception:  # noqa: BLE001 - that Python has no torch; try the next
                continue
    return None


def find_comfyui() -> tuple[list[str], Path] | tuple[None, str]:
    """Return (command, working folder), or (None, reason it couldn't be found)."""
    svc = settings()["services"]
    port = urlparse(settings()["comfyui"]["url"]).port or 8188
    extra = shlex.split(svc.get("comfyui_args") or "", posix=False)
    custom = (svc.get("comfyui_command") or "").strip()
    if custom:
        parts = shlex.split(custom, posix=False)
        parts = [p.strip('"') for p in parts]
        return parts, Path(parts[0]).parent
    base = Path(settings()["paths"]["comfyui_dir"])
    for folder in (base, base / "ComfyUI", base.parent / "ComfyUI_windows_portable" / "ComfyUI"):
        main = folder / "main.py"
        if main.exists():
            py = _python_for(folder)
            if py:
                return py + [str(main), "--port", str(port)] + extra, folder
    for bat in (base / "run_nvidia_gpu.bat", base.parent / "run_nvidia_gpu.bat"):
        if bat.exists():
            return ["cmd", "/c", str(bat)], bat.parent
    desktop = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "@comfyorgcomfyui-electron" / "ComfyUI.exe"
    if desktop.exists():
        return [str(desktop)], desktop.parent
    return None, (f"Couldn't find ComfyUI in {base}. Open Settings -> services -> comfyui_command "
                  "and enter how you normally start it (for example the path to run_nvidia_gpu.bat).")


def start_comfyui() -> str:
    cmd, where = find_comfyui()
    if not cmd:
        return str(where)
    proc = _spawn(cmd, Path(where), Paths().ensure().logs / "comfyui.log",
                  hidden=not cmd[0].lower().endswith("comfyui.exe"))
    write_json(Paths().root / "services.json", {"comfyui_pid": proc.pid, "command": cmd})
    return f"Starting ComfyUI ({Path(cmd[-1] if cmd[0] == 'cmd' else cmd[0]).name})..."


def _spawn(cmd: list[str], cwd: Path, log: Path, hidden: bool = True) -> subprocess.Popen:
    log.parent.mkdir(parents=True, exist_ok=True)
    out = open(log, "ab")
    kwargs: dict[str, Any] = {"cwd": str(cwd), "stdin": subprocess.DEVNULL, "stdout": out,
                              "stderr": subprocess.STDOUT}
    if os.name == "nt":
        kwargs["creationflags"] = (CREATE_NO_WINDOW if hidden else 0) | 0x00000200
    else:
        kwargs["start_new_session"] = True
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)  # don't leak the Studio's Python setup into ComfyUI
    env.pop("VIRTUAL_ENV", None)
    kwargs["env"] = env
    return subprocess.Popen(cmd, **kwargs)


def stop_started_comfyui() -> bool:
    """Stop the ComfyUI this program started (and only that one)."""
    info = read_json(Paths().root / "services.json", {}) or {}
    pid = info.get("comfyui_pid")
    if not pid:
        return False
    try:
        import psutil
        proc = psutil.Process(pid)
        for child in proc.children(recursive=True):
            child.terminate()
        proc.terminate()
        psutil.wait_procs([proc], timeout=10)
    except Exception:  # noqa: BLE001 - already gone
        pass
    write_json(Paths().root / "services.json", {})
    return True


def log_tail(name: str, lines: int = 25) -> str:
    path = Paths().logs / name
    if not path.exists():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


if __name__ == "__main__":  # quick manual check: python -m fofstudio.services
    print("Ollama up:", ollama_up(), "| start with:", find_ollama())
    print("ComfyUI up at:", comfy_url_up(), "| start with:", find_comfyui())
    sys.exit(0)
