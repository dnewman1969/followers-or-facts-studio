"""Settings: one TOML file, read once, with defaults for Dave's PC.

The settings file lives at `<data_dir>/settings.toml`. The data folder is found
from the FOF_DATA environment variable, then `config/data-dir.txt` in the repo,
then the default `F:/AI/fof-data`.
"""

from __future__ import annotations

import copy
import os
import tomllib
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = "F:/AI/fof-data"

DEFAULTS: dict[str, Any] = {
    "paths": {
        # Where the original truth-vlog research CSVs live. The importer falls
        # back to the copy shipped in seed/ when this folder doesn't exist.
        "truth_vlog_research": "C:/Projects/truth-vlog/research",
        "comfyui_dir": "F:/AI/ComfyUI",
        "ffmpeg": "ffmpeg",
        "ffprobe": "ffprobe",
        "font_regular": "",
        "font_bold": "",
    },
    "ollama": {
        "url": "http://127.0.0.1:11434",
        "writer_model": "qwen3:14b",
        # Checks must not be done by the same model that wrote the draft.
        "checker_model": "qwen3:8b",
        "num_ctx": 16384,
        "num_predict": 6000,
        "timeout_seconds": 900,
        "think": False,
    },
    "comfyui": {
        "url": "http://127.0.0.1:8188",
        "image_workflow": "comfy_workflows/zimage_turbo_t2i.json",
        "image_model_name": "Z-Image Turbo",
        "image_width": 1344,
        "image_height": 768,
        "video_workflow": "comfy_workflows/wan22_i2v_lightning.json",
        "video_model_name": "Wan 2.2 I2V 14B + Lightning",
        "video_width": 832,
        "video_height": 480,
        "video_frames": 81,
        "video_fps": 16,
        "music_workflow": "comfy_workflows/acestep_music.json",
        "music_model_name": "ACE-Step",
        "timeout_seconds": 3600,
    },
    "voice": {
        "engine": "kokoro",
        "voice": "bm_george",
        "speed": 0.95,
        "lang": "en-us",
        "tail_seconds": 0.6,
    },
    "captions": {
        # "auto" uses faster-whisper word timings when it is installed,
        # otherwise spreads the known script words across the audio.
        "engine": "auto",
        "whisper_model": "small.en",
        "max_chars": 42,
        "max_seconds": 3.2,
        "burn_in": False,
    },
    "video": {
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "encoder": "auto",
        "transition": "fade",
        "transition_seconds": 0.6,
        "music_volume": 0.18,
        "duck_music": True,
    },
    "storyboard": {
        "mode": "llm",
        "max_shots_per_scene": 5,
        "animate_shots_per_scene": 1,
    },
    "youtube": {
        "client_secrets": "",
        "privacy": "private",
        "category_id": "25",
        "made_for_kids": False,
    },
    "rendermode": {
        "suggested": [
            "steam.exe", "steamwebhelper.exe", "Discord.exe", "wallpaper64.exe",
            "wallpaper32.exe", "EpicGamesLauncher.exe", "EpicWebHelper.exe",
            "chrome.exe", "msedge.exe", "Spotify.exe",
        ],
        "never_touch": [
            "System", "Registry", "smss.exe", "csrss.exe", "wininit.exe",
            "winlogon.exe", "services.exe", "lsass.exe", "svchost.exe",
            "dwm.exe", "explorer.exe", "ollama.exe", "ollama app.exe",
            "python.exe", "pythonw.exe", "ffmpeg.exe", "nvcontainer.exe",
        ],
        "auto_for_gpu_stages": False,
    },
    "services": {
        # The desktop icon starts these if they aren't already running.
        "start_ollama": True,
        "start_comfyui": True,
        # Leave empty to find ComfyUI automatically. Otherwise the full command,
        # e.g. "F:/AI/ComfyUI/run_nvidia_gpu.bat" or "F:/AI/ComfyUI/venv/Scripts/python.exe main.py"
        "comfyui_command": "",
        "comfyui_args": "--disable-auto-launch",
        # Close the ComfyUI we started when the Studio closes (unless jobs are still running).
        "stop_comfyui_on_exit": True,
        "comfyui_wait_seconds": 240,
    },
    "pipeline": {
        "auto_continue": False,
        "channel_credit": (
            "Research trail: Knowledge Fight (knowledgefight.com). "
            "Every claim in this video is checked against primary sources, listed in the description."
        ),
    },
}


def data_dir() -> Path:
    env = os.environ.get("FOF_DATA")
    if env:
        return Path(env)
    pointer = REPO / "config" / "data-dir.txt"
    if pointer.exists():
        text = pointer.read_text(encoding="utf-8").strip()
        if text:
            return Path(text)
    return Path(DEFAULT_DATA_DIR)


def settings_path() -> Path:
    return data_dir() / "settings.toml"


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


_cache: dict[str, Any] | None = None


def settings(reload: bool = False) -> dict[str, Any]:
    global _cache
    if _cache is None or reload:
        path = settings_path()
        user: dict[str, Any] = {}
        if path.exists():
            with path.open("rb") as fh:
                user = tomllib.load(fh)
        _cache = _merge(DEFAULTS, user)
    return _cache


def repo_path(value: str) -> Path:
    """Resolve a path from settings: absolute stays, relative is from the repo."""
    p = Path(value)
    return p if p.is_absolute() else REPO / p


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    text = str(value).replace("\\", "/")
    return '"' + text.replace('"', '\\"') + '"'


def dump_toml(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for section, values in data.items():
        lines.append(f"[{section}]")
        for key, value in values.items():
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")
    return "\n".join(lines)


def save_settings(data: dict[str, Any]) -> Path:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_toml(data), encoding="utf-8")
    settings(reload=True)
    return path


class Paths:
    """Every folder in the data directory, in one place."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else data_dir()

    @property
    def db(self) -> Path:
        return self.root / "db" / "studio.sqlite"

    @property
    def episodes(self) -> Path:
        return self.root / "episodes"

    @property
    def models(self) -> Path:
        return self.root / "models"

    @property
    def source_copies(self) -> Path:
        return self.root / "source-copies"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def music_library(self) -> Path:
        return self.root / "music-library"

    @property
    def rendermode_state(self) -> Path:
        return self.root / "rendermode-state.json"

    @property
    def worker_lock(self) -> Path:
        return self.root / "worker.lock"

    def ensure(self) -> "Paths":
        for folder in (self.db.parent, self.episodes, self.models, self.source_copies,
                       self.logs, self.music_library):
            folder.mkdir(parents=True, exist_ok=True)
        return self
