"""ffmpeg/ffprobe helpers."""

from __future__ import annotations

import json
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import settings
from .util import StageError, run


def ffmpeg() -> str:
    return settings()["paths"]["ffmpeg"]


def ffprobe() -> str:
    return settings()["paths"]["ffprobe"]


def probe(path: Path) -> dict[str, Any]:
    result = run([ffprobe(), "-v", "error", "-show_format", "-show_streams", "-of", "json",
                  str(path)], label=f"reading {Path(path).name}")
    return json.loads(result.stdout)


def duration(path: Path) -> float:
    info = probe(path)
    value = info.get("format", {}).get("duration")
    if value is None:
        raise StageError(f"Can't tell how long {path} is.")
    return float(value)


def has_audio(path: Path) -> bool:
    return any(s.get("codec_type") == "audio" for s in probe(path).get("streams", []))


@lru_cache(maxsize=4)
def _encoders(binary: str) -> str:
    try:
        return run([binary, "-hide_banner", "-encoders"], label="listing encoders").stdout
    except StageError:
        return ""


def _nvenc_works(binary: str) -> bool:
    try:
        run([binary, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "color=black:s=256x256:d=0.1", "-c:v", "h264_nvenc", "-f", "null", "-"],
            label="testing NVENC", timeout=30)
        return True
    except StageError:
        return False


@lru_cache(maxsize=4)
def encoder(choice: str = "auto") -> dict[str, Any]:
    """h264_nvenc on the RTX 3060 when it works, libx264 otherwise."""
    binary = ffmpeg()
    if shutil.which(binary) is None and not Path(binary).exists():
        raise StageError(f"ffmpeg not found ({binary}). Install it (setup.ps1 does) or set "
                         "[paths] ffmpeg in Settings.")
    nvenc = {"name": "h264_nvenc", "draft": ["-preset", "p4", "-cq", "23"],
             "final": ["-preset", "p6", "-rc", "vbr", "-cq", "19", "-b:v", "0"]}
    x264 = {"name": "libx264", "draft": ["-preset", "veryfast", "-crf", "20"],
            "final": ["-preset", "medium", "-crf", "18"]}
    if choice == "libx264":
        return x264
    if choice in ("auto", "h264_nvenc") and "h264_nvenc" in _encoders(binary) and _nvenc_works(binary):
        return nvenc
    if choice == "h264_nvenc":
        raise StageError("NVENC was requested but doesn't work here (driver or ffmpeg build).")
    return x264
