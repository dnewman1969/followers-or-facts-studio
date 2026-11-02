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
    from . import bible, unreal_bridge
    if unreal_bridge.pending():          # Unreal finished since last time: turn its captures into guides
        unreal_bridge.bring_in()
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


# Which shots a room layout helps: places and people in them. A close-up of a document, an object or a symbol
# has nothing to do with the room's layout, so it's painted freely (research "AI film crew production pipeline").
LAYOUT_SHOWS = {"", "place", "building", "crowd from behind", "single figure from behind", "broadcast or media",
                "machine or technology"}
# the Unreal camera that matches the shot the director asked for
CAMERA_FOR = {"establishing": "wide", "wide": "wide", "tracking": "wide", "crane": "high", "dolly": "medium",
              "medium": "medium", "two shot": "medium", "over-the-shoulder": "side", "reaction": "close",
              "close-up": "close", "silhouette": "side", "bird's eye": "high", "worm's eye": "low",
              "high angle": "high", "overhead": "high", "low angle": "low", "ground level": "low"}


def guide_for(ep: Episode, shot: dict) -> Path | None:
    """The guide picture for this shot, or None. Owlbert sets, caricatures and close-ups of things are painted
    freely. Depth guides are preferred (outlines of a grey blockout have no edges on its walls, so they made the
    paintings plain and grey); the camera is the one matching the shot's framing."""
    if shot.get("kind") not in ("broll",) or shot.get("shows", "") not in LAYOUT_SHOWS:
        return None
    look = shot.get("look") or {}
    if look.get("shot_type") in ("extreme close-up",):
        return None
    scene_id = shot.get("scene_id") or shot["shot_id"].rsplit("-s", 1)[0]
    found = guides(ep, scene_id)
    if not found:
        return None
    depth = [p for p in found if "depth" in p.stem] or found
    want = CAMERA_FOR.get(look.get("angle", "")) if look.get("angle") not in ("", "eye level", None) else None
    want = want or CAMERA_FOR.get(look.get("shot_type", ""))
    if want:
        match = [p for p in depth if p.stem.split("-")[0] == want]
        if match:
            return match[0]
    try:
        n = int(shot["shot_id"].rsplit("-s", 1)[1]) - 1
    except (IndexError, ValueError):
        n = 0
    return depth[n % len(depth)]
