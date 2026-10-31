"""Unreal Engine, done for you (Dave, 2026-10-31: "make a script that can do what you need, that way it will be
done correctly").

  prepare(ep)   writes the job (the places in this video's bible) and a ready-to-run copy of the Unreal script,
                fof_unreal_guides.py, in <data>/unreal/. In Unreal: Tools > Execute Python Script > that file.
                The script builds a rough set for each place from Unreal's built-in shapes, puts six cameras
                around it, captures a depth picture and a plain layout picture from each, saves them, and removes
                everything it added (data/unreal/fof_unreal_guides.py).
  bring_in()    turns what Unreal saved into guide pictures: depth (near = white) and outlines, at the painting's
                size, in <data>/control-maps/<place id>/ where the storyboard finds them (controlmaps.py). It runs
                by itself when the storyboard looks for guides, so pressing Make pictures is enough.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import numpy as np

from .config import data_dir, settings
from .episode import Episode
from .util import StageError, read_json, utc_now, write_json

SCRIPT = Path(__file__).resolve().parent / "data" / "unreal" / "fof_unreal_guides.py"


def folder() -> Path:
    return data_dir() / "unreal"


def out_dir() -> Path:
    return folder() / "out"


def prepare(ep: Episode) -> dict[str, Any]:
    """The job for this video's places, and the script with the job's path filled in."""
    from . import bible
    b = bible.load(ep)
    places = [{"id": k, **{f: v.get(f, "") for f in ("name", "architecture", "props", "colours")}}
              for k, v in (b.get("locations") or {}).items()]
    if not places:
        raise StageError("This video's bible has no places yet. Approve the script, then press Make pictures once "
                         "(it writes the bible), then come back here.")
    folder().mkdir(parents=True, exist_ok=True)
    out_dir().mkdir(parents=True, exist_ok=True)
    (out_dir() / "done.json").unlink(missing_ok=True)
    job = {"out": str(out_dir()), "places": places, "episode": ep.project_id, "made_at": utc_now()}
    write_json(folder() / "job.json", job)
    script = folder() / "fof_unreal_guides.py"
    script.write_text(SCRIPT.read_text(encoding="utf-8").replace("{{JOB_PATH}}", str(folder() / "job.json")),
                      encoding="utf-8")
    return {"script": script, "job": folder() / "job.json", "places": places}


def pending() -> list[Path]:
    """Captures Unreal saved that haven't been turned into guide pictures yet."""
    if not out_dir().is_dir():
        return []
    return sorted(p for p in out_dir().glob("*/*.json") if p.name != "place.json")


def _depth(raw: Path, w: int, h: int, size: tuple[int, int]) -> np.ndarray:
    """Unreal's depth (centimetres per pixel) as 0..255 at the painting's size: near = white, far = dark."""
    import cv2
    d = np.fromfile(raw, dtype="<f4")
    if d.size != w * h:
        raise StageError(f"{raw.name} isn't the size Unreal said it was")
    d = d.reshape(h, w)
    valid = np.isfinite(d) & (d > 0) & (d < 1e6)         # the sky / nothing comes back huge
    if not valid.any():
        raise StageError(f"{raw.name} saw nothing (the set wasn't in front of the camera)")
    near, far = np.percentile(d[valid], 1), np.percentile(d[valid], 99)
    norm = np.zeros_like(d)
    norm[valid] = 1.0 - np.clip((d[valid] - near) / max(1e-3, far - near), 0, 1)
    return cv2.resize((norm * 255).astype(np.uint8), size, interpolation=cv2.INTER_LANCZOS4)


def _lines(layout: Path | None, depth: np.ndarray | None, w: int, h: int, size: tuple[int, int]) -> np.ndarray:
    """Outlines: where the depth jumps (the edge of every wall, desk and figure) plus the creases the lighting
    shows in the plain grey layout picture. Either alone is enough, so a dark capture still gives outlines."""
    import cv2
    edges = np.zeros((size[1], size[0]), np.uint8)
    if depth is not None:
        edges |= cv2.Canny(cv2.GaussianBlur(depth, (5, 5), 0), 12, 36)
    if layout is not None and layout.exists():
        rgb = np.fromfile(layout, dtype=np.uint8)
        if rgb.size != w * h * 3:
            raise StageError(f"{layout.name} isn't the size Unreal said it was")
        grey = cv2.cvtColor(rgb.reshape(h, w, 3), cv2.COLOR_RGB2GRAY)
        grey = cv2.resize(grey, size, interpolation=cv2.INTER_CUBIC)
        edges |= cv2.Canny(cv2.GaussianBlur(grey, (5, 5), 0), 30, 90)
    return edges


def bring_in() -> dict[str, Any]:
    """Turn every finished Unreal capture into guide pictures. Returns what was made, by place."""
    from PIL import Image

    from .controlmaps import folder_for_location
    cfg = settings()["comfyui"]
    size = (int(cfg["image_width"]), int(cfg["image_height"]))
    made: dict[str, list[str]] = {}
    problems: list[str] = []
    for meta_path in pending():
        meta = read_json(meta_path) or {}
        place = meta_path.parent.name
        cam = meta.get("camera") or meta_path.stem
        dest = folder_for_location(place)
        dest.mkdir(parents=True, exist_ok=True)
        try:
            depth = meta_path.with_name(f"{cam}.depth.bin")
            layout = meta_path.with_name(f"{cam}.layout.bin")
            w, h = int(meta["width"]), int(meta["height"])
            dmap = _depth(depth, w, h, size) if depth.exists() else None
            if dmap is not None:
                Image.fromarray(dmap, "L").convert("RGB").save(dest / f"{cam}-depth.png")
                made.setdefault(place, []).append(f"{cam}-depth.png")
            if dmap is not None or layout.exists():
                lines = _lines(layout, dmap, w, h, size)
                if lines.any():
                    Image.fromarray(lines, "L").convert("RGB").save(dest / f"{cam}-lines.png")
                    made.setdefault(place, []).append(f"{cam}-lines.png")
        except (StageError, KeyError, ValueError, OSError) as exc:
            problems.append(f"{place}/{cam}: {exc}")
            continue
        for f in (meta_path, meta_path.with_name(f"{cam}.depth.bin"), meta_path.with_name(f"{cam}.layout.bin")):
            f.unlink(missing_ok=True)
    for place_dir in list(out_dir().glob("*")) if out_dir().is_dir() else []:
        if place_dir.is_dir() and not any(p.suffix == ".bin" for p in place_dir.iterdir()):
            if (place_dir / "place.json").exists():
                folder_for_location(place_dir.name).mkdir(parents=True, exist_ok=True)
                shutil.copy2(place_dir / "place.json", folder_for_location(place_dir.name) / "place.json")
            shutil.rmtree(place_dir, ignore_errors=True)
    if made or problems:
        write_json(folder() / "last-import.json", {"made": made, "problems": problems, "at": utc_now()})
    return {"made": made, "problems": problems}


def status(ep: Episode) -> list[dict[str, Any]]:
    """For each place in this video: how many guide pictures it has."""
    from . import bible
    from .controlmaps import KINDS, folder_for_location
    out = []
    for pid, loc in (bible.load(ep).get("locations") or {}).items():
        d = folder_for_location(pid)
        n = len([p for p in d.iterdir() if p.suffix.lower() in KINDS]) if d.is_dir() else 0
        out.append({"id": pid, "name": loc.get("name", pid), "guides": n, "folder": d})
    return out

