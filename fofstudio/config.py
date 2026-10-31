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
        "num_ctx": 16384,               # starting room; grows by itself when an answer needs more
        "num_predict": 6000,
        "max_ctx": 32768,               # the most it may grow to (more context = more memory)
        "max_predict": 16384,
        "timeout_seconds": 900,
        "think": False,
        "top_p": 0.8,               # Qwen 3's recommended settings with thinking off
        "top_k": 20,
        "presence_penalty": 0.5,    # discourages repeating itself in long scripts
        "format_check": True,       # test once per model whether Ollama obeys the answer format (llm.py)
    },
    # The model for each job (empty = [ollama] writer_model; checks = checker_model). Install a model with
    # "ollama pull <name>" first. Suggestions from the research "Best local AI models per job":
    # research_plan qwen3.5:9b, script_write gemma4:12b (test it against qwen3:14b first).
    "models": {
        "research_plan": "",
        "research_quotes": "",
        "research_summary": "",
        "stories": "",
        "script_plan": "",
        "script_write": "",
        "storyboard": "",
        "director": "",
        "vision": "qwen3-vl:8b-instruct",   # sees pictures (Apache-2.0); describes caricature references.
                                            # (plain "qwen3-vl:8b" is the thinking version: it never just answers)
        "vision_backups": ["gemma4:e4b", "qwen2.5vl:7b"],   # tried in turn if the vision model fails
        "claims": "",
        "book": "",
        "checks": "",
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
        "t2v_workflow": "comfy_workflows/wan22_ti2v5b_t2v.json",
        "t2v_model_name": "Wan 2.2 TI2V-5B",
        "t2v_width": 1280,
        "t2v_height": 704,
        "t2v_frames": 121,
        "t2v_fps": 24,
        "music_workflow": "comfy_workflows/acestep_music.json",
        "depth_workflow": "comfy_workflows/depth_anything_v2_small.json",
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
        "smooth_clips": True,           # blend in-between frames so AI clips (16 fps) play smoothly
        "check_clips": True,            # catch broken animated clips (sudden jumps, black frames): redo once, then 2.5D
        "finish_ai_clips": True,        # animated clips: interpolate, deflicker, upscale, match colour to the still
        "open_folder_after_render": True,
    },
    "storyboard": {
        "mode": "llm",
        "max_shots_per_scene": 5,       # (old setting, no longer used)
        "shot_limit_per_scene": 24,
        "candidates_per_shot": 2,       # versions painted of each shot (1-3); the first is used unless you pick another
        "animate_shots_per_scene": 1,   # (old setting; animation_level decides now)
        "animation_level": "balanced",  # fast (1 in 10 shots animated by Wan) | balanced (1 in 3) | full (every shot)
        "parallax": True,               # every other picture moves in 2.5D (depth) instead of a flat zoom
        "t2v_shots_per_scene": 0,       # Wan 2.2 text-to-video b-roll clips per scene (needs the TI2V-5B model)
        "quality_review": True,         # the vision model checks every painted picture; failures are repainted
        "auto_redo": True,              # the Quality Review re-plans failing scenes once, automatically
        "review_repaints": 12,          # at most this many pictures repainted per run by the review
    },
    "claims": {
        "check_sentences": True,  # after writing, a different model checks every fact sentence against its
                                  # scene's own evidence and takes out what isn't backed (claimcheck.py)
    },
    "director": {
        "enabled": True,          # the Virtual Director reviews every shot before it's painted (director.py)
        "ai_repairs": 30,         # most shots per run the director AI rewrites; after that the program reframes
        "tries": 2,               # AI rewrites per failing shot before the program reframes it itself
    },
    "media": {
        "enabled": True,          # the storyboard may use real, free-licence pictures (mediafinder.py)
        "sources": ["commons", "openverse"],
    },
    "book": {
        "author": "Followers or Facts",   # the name on the cover and the copyright line
        "min_pages": 45,                  # a subject with this much material is called book-sized
    },
    "youtube": {                        # uploading is done on YouTube's own page (no Google setup)
        "privacy": "private",
        "category_id": "27",            # Education
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
    "research": {
        # quick: ~3 searches per claim, normal: ~5, deep: ~8 (each adds a few minutes)
        "depth": "normal",
        "contact_email": "",  # optional: some sites ask bots for a contact address
        "use_web_search": True,
        "use_wayback": True,
        "archive_new_links": True,
        # free keys that unlock more sources; leave blank to skip that source
        "courtlistener_token": "",
        "govinfo_key": "",
        "factcheck_key": "",
        "archive_access_key": "",
        "archive_secret_key": "",
    },
    "sound": {
        "device": "",               # speaker id (blank = Windows' default speaker)
        "listen_volume": 80,        # 0-100, how loud the preview plays on this PC
        "media_backend": "auto",    # auto | ffmpeg | windows (restart the Studio after changing)
        "speech_db": 0.0,           # default mix for new videos (each video keeps its own mix)
        "music_db": -14.0,
        "master_db": 0.0,
        "normalize_loudness": True, # make every video equally loud for YouTube
        "loudness_lufs": -14.0,
    },
    "owl": {
        "voice": "bm_george:0.7,bm_fable:0.3",
        "speed": 0.93,
        "pitch_semitones": 1.0,
        "presenter": True,
        "presenter_corner": "bottom_right",
        "presenter_height": 0.34,
        "moves": True,
        "in_scenes": False,   # also stand big Owlbert inside some pictures (off: only the corner Owlbert)
        "rhubarb": "",
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
        # utf-8-sig drops the invisible marker Windows PowerShell 5 adds to UTF-8 files
        text = pointer.read_text(encoding="utf-8-sig").strip().strip('"').strip()
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
