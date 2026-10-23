"""Production: the editing timeline.

Tracks (top to bottom, like a video editor):
  V1 Video    intro bumper, every approved clip in scene order, outro bumper
  V2 Owlbert  when the talking owl presenter shows in the corner
  A1 Speech   Owlbert reading each scene of the script
  A2 Music    the music bed (ducked under his voice when rendered)

"Assemble" lines everything up automatically: each scene's clips are stretched to fill the
time Owlbert takes to read that scene. You can then drag, trim and nudge anything in the
editor; the timeline is saved to production.json and the Render stage follows it exactly.
"""

from __future__ import annotations

from typing import Any

from .. import media, owl
from ..config import settings
from ..episode import Episode
from ..util import StageError, read_json, utc_now, write_json
from .base import BLOCK, OK, WARN, Check, Context
from .script import load as load_script
from .video import load_plan

LEAD = 0.35          # Owlbert starts talking this long after his scene appears
TAIL = 0.6           # breathing room after each scene
FADE = 0.4           # cross-fade between clips inside a scene
SCENE_FADE = 0.6     # cross-fade between scenes


def path(ep: Episode):
    return ep.path("production.json")


MIX_KEYS = ("speech_db", "music_db", "master_db")


def mix(tl: dict[str, Any]) -> dict[str, float]:
    """This video's sound mix in dB: its own if you moved the sliders, else the defaults from Settings."""
    snd = settings()["sound"]
    own = tl.get("mix") or {}
    return {k: float(own.get(k, snd[k])) for k in MIX_KEYS}


def load(ep: Episode) -> dict[str, Any]:
    return read_json(path(ep), {}) or {}


def save(ep: Episode, tl: dict[str, Any], edited: bool = True) -> None:
    tl["edited"] = edited
    tl["saved_at"] = utc_now()
    tl["duration"] = timeline_end(tl)
    write_json(path(ep), tl)


def timeline_end(tl: dict[str, Any]) -> float:
    ends = [c["start"] + c["duration"] for track in ("video", "speech") for c in tl.get(track, [])]
    return round(max(ends, default=0.0), 3)


def make_bumpers(ep: Episode, title: str) -> tuple[str, str]:
    v = settings()["video"]
    intro = ep.path("video", "bumper-intro.mp4")
    outro = ep.path("video", "bumper-outro.mp4")
    if not intro.exists():
        owl.bumper("intro", title, intro, int(v["width"]), int(v["height"]), int(v["fps"]))
    if not outro.exists():
        owl.bumper("outro", title, outro, int(v["width"]), int(v["height"]), int(v["fps"]))
    return ep.rel(intro), ep.rel(outro)


def _fit_lengths(ep: Episode, shots: list[dict[str, Any]], total: float) -> list[float]:
    """Share a scene's time between its shots without repeating anything: animated clips keep about their
    own length (up to a little slow motion), and camera moves and cards stretch or shrink to fill the rest."""
    fixed, flex = {}, []
    for i, s in enumerate(shots):
        if s["clip"].get("still") or s["clip"].get("kind") == "camera_move":
            flex.append(i)
        else:
            try:
                fixed[i] = media.duration(ep.abs(s["clip"]["path"]))
            except Exception:  # noqa: BLE001 - treat an unreadable clip like a still
                flex.append(i)
    lengths = [0.0] * len(shots)
    for i, d in fixed.items():
        lengths[i] = d
    rest = total - sum(fixed.values())
    if flex:
        want = [max(1.5, float(shots[i].get("seconds", 4.0))) for i in flex]
        scale = max(rest, 1.5 * len(flex)) / sum(want)
        for i, w in zip(flex, want):
            lengths[i] = max(1.5, w * scale)
    elif fixed and rest > 0:   # only animated clips: slow them a little (smoothly), then hold the last frame
        factor = total / sum(fixed.values())
        for i in fixed:
            lengths[i] = fixed[i] * factor
    elif fixed and rest < 0:   # too much footage: trim clips evenly
        factor = total / sum(fixed.values())
        for i in fixed:
            lengths[i] = max(1.0, fixed[i] * factor)
    return lengths


def assemble(ep: Episode, progress=lambda t, p=None: None) -> dict[str, Any]:
    script = load_script(ep)
    narration = read_json(ep.path("audio", "narration.json"), {}) or {}
    plan = load_plan(ep)
    if not plan["shots"]:
        raise StageError("Make and approve the video clips first.")
    if not narration:
        raise StageError("Make Owlbert's speech track first (press Make speech track).")
    progress("Making the intro and outro bumpers", 10)
    intro, outro = make_bumpers(ep, script["title"] or ep.title)
    v = settings()["video"]
    tl: dict[str, Any] = {"fps": int(v["fps"]), "width": int(v["width"]), "height": int(v["height"]),
                          "video": [], "speech": [], "music": [], "owl": []}
    t = 0.0
    intro_len = media.duration(ep.abs(intro))
    tl["video"].append({"id": "intro", "src": intro, "start": 0.0, "duration": round(intro_len, 3),
                        "inpoint": 0.0, "label": "Intro bumper", "kind": "bumper", "ai": False, "scene_id": "INTRO"})
    t = intro_len - SCENE_FADE
    by_scene: dict[str, list[dict[str, Any]]] = {}
    for s in plan["shots"]:
        by_scene.setdefault(s["scene_id"], []).append(s)
    progress("Lining the clips up with Owlbert's voice", 50)
    for sc in script["scenes"]:
        m = narration.get(sc["scene_id"])
        shots = [s for s in by_scene.get(sc["scene_id"], []) if s.get("clip")]
        if not shots:
            continue
        scene_len = (LEAD + m["seconds"] + TAIL) if m else sum(s["seconds"] for s in shots)
        lengths = _fit_lengths(ep, shots, scene_len + FADE * (len(shots) - 1))
        if m:
            tl["speech"].append({"id": f"say-{sc['scene_id']}", "src": m["path"], "start": round(t + LEAD, 3),
                                 "duration": round(m["seconds"], 3), "scene_id": sc["scene_id"],
                                 "text": sc["narration"]})
            if settings()["owl"]["presenter"]:
                tl["owl"].append({"id": f"owl-{sc['scene_id']}", "start": round(t + LEAD, 3),
                                  "duration": round(m["seconds"], 3)})
        for k, (s, length) in enumerate(zip(shots, lengths)):
            last = k == len(shots) - 1
            overlap = SCENE_FADE if last else FADE
            dur = length + (SCENE_FADE - FADE if last else 0.0)
            item = {"id": s["shot_id"], "src": s["clip"]["path"], "start": round(t, 3),
                    "duration": round(dur, 3), "inpoint": 0.0, "label": s["shot_id"],
                    "kind": "clip", "ai": bool(s["clip"].get("ai")), "scene_id": sc["scene_id"]}
            if s["clip"].get("still"):  # camera moves are redrawn at exactly this length when rendering
                item["still"], item["camera"] = s["clip"]["still"], s["clip"].get("camera", "zoom_in")
            tl["video"].append(item)
            t += dur - overlap
    outro_len = media.duration(ep.abs(outro))
    tl["video"].append({"id": "outro", "src": outro, "start": round(t, 3), "duration": round(outro_len, 3),
                        "inpoint": 0.0, "label": "Outro bumper", "kind": "bumper", "ai": False, "scene_id": "OUTRO"})
    end = t + outro_len
    music = read_json(ep.path("audio", "music", "music.json"))
    music_ok = ep.stage_status("music")["status"] == "approved" and not \
        (ep.stage_status("music").get("note") or "").startswith("SKIPPED")
    if music and music_ok and ep.abs(music["path"]).exists():
        tl["music"].append({"id": "music", "src": music["path"], "start": 0.0, "duration": round(end, 3),
                            "volume": 1.0})
    return tl


def run(ctx: Context) -> None:
    ep = ctx.episode
    existing = load(ep)
    if existing.get("edited") and not ctx.options.get("rebuild"):
        ctx.progress("Keeping your edited timeline (choose Rebuild to start over).", 100)
        return
    tl = assemble(ep, ctx.progress)
    save(ep, tl, edited=False)
    ctx.progress(f"Timeline ready: {timeline_end(tl) / 60:.1f} minutes. Preview it, adjust, then render.", 100)


def check(ep: Episode) -> list[Check]:
    tl = load(ep)
    if not tl:
        return [Check(BLOCK, "No timeline yet. Press Assemble timeline.")]
    out: list[Check] = []
    missing = [c["label"] if "label" in c else c["id"] for track in ("video", "speech", "music")
               for c in tl.get(track, []) if not ep.abs(c["src"]).exists()]
    if missing:
        out.append(Check(BLOCK, f"Files missing from the timeline: {', '.join(missing[:6])}"))
    narration = read_json(ep.path("audio", "narration.json"), {}) or {}
    on_track = {c["scene_id"] for c in tl.get("speech", [])}
    lost = [s for s in narration if s not in on_track]
    if lost:
        out.append(Check(BLOCK, f"Owlbert's lines for {', '.join(lost)} aren't on the speech track. Rebuild."))
    for c in tl.get("speech", []):
        m = narration.get(c["scene_id"])
        if m and m["path"] != c["src"]:
            out.append(Check(BLOCK, f"{c['scene_id']}: the speech track uses an old recording. Rebuild."))
    video = sorted(tl.get("video", []), key=lambda c: c["start"])
    for a, b in zip(video, video[1:]):
        gap = b["start"] - (a["start"] + a["duration"])
        if gap > 0.3:
            out.append(Check(WARN, f"{gap:.1f} s of black between {a['label']} and {b['label']}."))
    end_v = max((c["start"] + c["duration"] for c in video), default=0)
    end_s = max((c["start"] + c["duration"] for c in tl.get("speech", [])), default=0)
    if end_s > end_v:
        out.append(Check(WARN, "Owlbert keeps talking after the picture ends."))
    if not any(c.level == BLOCK for c in out):
        out.append(Check(OK, f"Timeline: {timeline_end(tl) / 60:.1f} min, {len(video)} video clips, "
                             f"{len(tl.get('speech', []))} speech lines. Press Preview to watch it."))
    return out
