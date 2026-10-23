"""Small helpers shared by every module."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


class StageError(RuntimeError):
    """A stage could not finish. The message is shown to Dave as-is, so it says
    what went wrong and what to do about it."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slug(text: str, limit: int = 48) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return out[:limit].strip("-") or "untitled"


def read_json(path: Path, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> Path:
    """Write JSON atomically so a crash never leaves half a file behind."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


def write_text(path: Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)
    return path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_list(value: str | None) -> list[str]:
    """truth-vlog stores lists as semicolon-separated text."""
    if not value:
        return []
    return [part.strip() for part in value.split(";") if part.strip()]


def run(cmd: list[str], label: str, timeout: float | None = None,
        cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a command and turn a failure into a readable StageError."""
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout, cwd=cwd, **kwargs)
    except FileNotFoundError as exc:
        raise StageError(f"{label}: could not start {cmd[0]!r}. Is it installed and on PATH? ({exc})")
    except subprocess.TimeoutExpired:
        raise StageError(f"{label}: timed out after {timeout:.0f} seconds.")
    if result.returncode != 0:
        tail = "\n".join((result.stderr or result.stdout or "").strip().splitlines()[-15:])
        raise StageError(f"{label} failed (exit {result.returncode}):\n{tail}")
    return result


def chunks(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


_SYLLABLE_RE = re.compile(r"[aeiouy]+")


def _syllables(word: str) -> int:
    word = word.lower().strip(".,!?;:'\"()")
    if not word:
        return 0
    if len(word) <= 3:
        return 1
    word = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", word)
    word = re.sub(r"^y", "", word)
    return max(1, len(_SYLLABLE_RE.findall(word)))


def reading_grade(text: str) -> float:
    """Flesch-Kincaid grade level. Rough, but good enough to flag dense writing."""
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", text)
    if not sentences or not words:
        return 0.0
    syllables = sum(_syllables(w) for w in words)
    return round(0.39 * len(words) / len(sentences) + 11.8 * syllables / len(words) - 15.59, 1)


def normalize_for_match(text: str) -> str:
    """Make quote matching ignore curly quotes, dashes, case and spacing."""
    table = {
        "‘": "'", "’": "'", "“": '"', "”": '"',
        "–": "-", "—": "-", " ": " ",
    }
    for a, b in table.items():
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip().lower()


def reveal(path) -> None:
    """Open the folder holding a file, with the file selected (Explorer on Windows)."""
    import os
    import subprocess
    import sys
    from pathlib import Path
    path = Path(path).resolve()
    if sys.platform == "win32":
        # Explorer wants one argument: /select,"C:\path with spaces\file.mp4"
        subprocess.Popen(f'explorer /select,"{path}"')
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        folder = path.parent if path.is_file() else path
        if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            subprocess.Popen(["xdg-open", str(folder)])
