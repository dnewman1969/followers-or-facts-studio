"""Guide pictures from Unreal Engine (Dave, 2026-10-31: "I have access to Unreal Engine and could have access to
free pose skeletons").

From the research "AI film director storyboard pipeline": you can block out a set in Unreal (free for videos: Epic
charges no royalty on linear content such as YouTube videos) and render guide passes from saved cameras: depth,
outlines (lineart), and pose skeletons from a mannequin (DWPose on a mannequin render; Mixamo animations are
royalty-free for films). The picture model then paints in the video's style ON that layout, through the
Z-Image Turbo Fun ControlNet, so a place keeps the same layout from shot to shot and a figure holds a clean pose
that animates well.

Where to put them (docs/UNREAL.md):
    <data folder>/control-maps/<location id>/*.png     a place from the film's bible (bible.json), any camera
    <episode folder>/control/<scene id>/*.png          just this scene (wins over the place's)
Each shot of the scene takes the next guide picture in turn (sorted by name), so different saved cameras give
different angles. No guide pictures: shots are painted from words, as before.
"""

from __future__ import annotations

from pathlib import Path

from .config import data_dir
from .episode import Episode

KINDS = (".png", ".jpg", ".jpeg", ".webp")


def folder_for_location(location_id: str) -> Path:
    return data_dir() / "control-maps" / (location_id or "_none")


def guides(ep: Episode, scene_id: str) -> list[Path]:
    from . import bible
    own = ep.path("control", scene_id)
    if own.is_dir():
        found = sorted(p for p in own.iterdir() if p.suffix.lower() in KINDS)
        if found:
            return found
    loc = ((bible.load(ep).get("scenes") or {}).get(scene_id) or {}).get("location") or ""
    place = folder_for_location(loc)
    if loc and place.is_dir():
        return sorted(p for p in place.iterdir() if p.suffix.lower() in KINDS)
    return []


def guide_for(ep: Episode, shot: dict) -> Path | None:
    """The guide picture for this shot, or None. Owlbert sets and caricatures are painted freely."""
    if shot.get("kind") not in ("broll",):
        return None
    scene_id = shot.get("scene_id") or shot["shot_id"].rsplit("-s", 1)[0]
    found = guides(ep, scene_id)
    if not found:
        return None
    try:
        n = int(shot["shot_id"].rsplit("-s", 1)[1]) - 1
    except (IndexError, ValueError):
        n = 0
    return found[n % len(found)]
