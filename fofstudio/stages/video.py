"""Video: turn every picked picture into a moving clip.

Step 1, "Write scene instructions" (video_plan): for each picture the local AI writes how
the shot plays out in plain words, the motion prompt for the animation model, the camera
move, how long it lasts, and HOW it will be made:
    animate      Wan 2.2 image-to-video in ComfyUI (about 5-6 minutes per clip on the 3060)
    camera_move  a slow zoom or pan over the still, made by ffmpeg in seconds
You can edit any of it. Step 2, "Make the clips" (video), makes every clip.
"""

from __future__ import annotations

from typing import Any

from ..comfy import Comfy, new_seed, run_template
from ..config import settings
from ..engines.render import CAMERA_MOVES, Segment, Timeline, _render_segment
from ..episode import Episode
from ..llm import Ollama
from ..util import StageError, read_json, sha256_text, utc_now, write_json
from .base import BLOCK, OK, WARN, Check, Context
from .storyboard import shots as board_shots

MOTION_SUFFIX = "slow, subtle cinematic motion, steady camera, natural movement, no sudden changes"
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "how_it_plays": {"type": "string"},
        "motion_prompt": {"type": "string"},
        "camera": {"type": "string", "enum": CAMERA_MOVES},
        "seconds": {"type": "number"},
    },
    "required": ["how_it_plays", "motion_prompt", "camera", "seconds"],
}


def plan_path(ep: Episode):
    return ep.path("video", "plan.json")


def load_plan(ep: Episode) -> dict[str, Any]:
    return read_json(plan_path(ep), {"shots": []}) or {"shots": []}


def save_plan(ep: Episode, plan: dict[str, Any]) -> None:
    write_json(plan_path(ep), plan)


def _digest(s: dict[str, Any]) -> str:
    return sha256_text(f"{s['method']}|{s['motion_prompt']}|{s['camera']}|{s['seconds']}|{s['image']}")


def plan(ctx: Context) -> None:
    ep = ctx.episode
    shots = board_shots(ep)
    if not shots:
        raise StageError("Approve the Storyboard first (pick at least one picture per scene).")
    old = {s["shot_id"]: s for s in load_plan(ep)["shots"]}
    per_scene = int(settings()["storyboard"]["animate_shots_per_scene"])
    animated: dict[str, int] = {}
    out = []
    llm = Ollama()
    for n, shot in enumerate(shots):
        ctx.check_cancel()
        prev = old.get(shot["shot_id"])
        if prev and prev["image"] == shot["image"]["path"] and not ctx.options.get("redo_all"):
            out.append(prev)
            continue
        if shot["type"] == "ai_image":
            ctx.progress(f"Writing instructions for {shot['shot_id']} ({n + 1}/{len(shots)})",
                         100 * n / len(shots))
            p = llm.chat_json([
                {"role": "system", "content": (
                    "You direct short documentary b-roll shots made from a still picture. Describe how "
                    "the shot plays out in one or two plain sentences, then write a motion prompt for an "
                    "image-to-video model (what moves and how: drifting smoke, flickering light, slow "
                    "push-in; never add people, text or logos), pick a camera move, and a length of "
                    "3 to 6 seconds.")},
                {"role": "user", "content": f"Picture: {shot['prompt']}"},
            ], PLAN_SCHEMA, temperature=0.5)
            animate = animated.get(shot["scene_id"], 0) < per_scene
            animated[shot["scene_id"]] = animated.get(shot["scene_id"], 0) + int(animate)
            entry = {"how_it_plays": p["how_it_plays"], "motion_prompt": p["motion_prompt"],
                     "camera": p["camera"] if p["camera"] in CAMERA_MOVES else "zoom_in",
                     "seconds": max(2.0, min(8.0, float(p["seconds"]))),
                     "method": "animate" if animate else "camera_move"}
        else:
            entry = {"how_it_plays": f"{shot['type'].replace('_', ' ')} holds on screen: \"{shot.get('text', '')[:80]}\"",
                     "motion_prompt": "", "camera": "zoom_in" if shot["type"] == "quote_card" else "static",
                     "seconds": 4.0 if shot["type"] == "title_card" else 6.0, "method": "camera_move"}
        out.append({"shot_id": shot["shot_id"], "scene_id": shot["scene_id"], "type": shot["type"],
                    "image": shot["image"]["path"], "raw": shot["image"].get("raw"),
                    "prompt": shot.get("prompt", ""), **entry, "clip": None, "approved": False})
    save_plan(ep, {"shots": out, "made_at": utc_now()})
    ctx.progress("Scene instructions written. Read them, change anything, then make the clips.", 100)


def update_shot(ep: Episode, shot_id: str, **fields: Any) -> None:
    p = load_plan(ep)
    for s in p["shots"]:
        if s["shot_id"] == shot_id:
            s.update(fields)
            if any(k in fields for k in ("motion_prompt", "camera", "seconds", "method")):
                s["approved"] = False
    save_plan(ep, p)


def check_plan(ep: Episode) -> list[Check]:
    p = load_plan(ep)
    if not p["shots"]:
        return [Check(BLOCK, "No scene instructions yet. Press Write scene instructions.")]
    current = {s["shot_id"] for s in board_shots(ep)}
    if current != {s["shot_id"] for s in p["shots"]}:
        return [Check(BLOCK, "The picked pictures changed. Write scene instructions again.")]
    n = sum(1 for s in p["shots"] if s["method"] == "animate")
    return [Check(OK, f"{len(p['shots'])} shots planned: {n} animated with Wan 2.2 "
                      f"(about {n * 6} minutes), the rest with camera moves.")]


def run(ctx: Context) -> None:
    ep = ctx.episode
    p = load_plan(ep)
    if not p["shots"]:
        raise StageError("Write and approve the scene instructions first.")
    cfg = settings()["comfyui"]
    vid = settings()["video"]
    redo = set(ctx.options.get("redo") or [])
    client = None
    total = len(p["shots"])
    for n, s in enumerate(p["shots"]):
        ctx.check_cancel()
        digest = _digest(s)
        if s.get("clip") and s["clip"].get("digest") == digest and ep.abs(s["clip"]["path"]).exists() \
                and s["shot_id"] not in redo:
            continue
        if s["method"] == "animate":
            if not s.get("raw"):
                raise StageError(f"{s['shot_id']} has no AI picture to animate; set it to camera_move.")
            ctx.progress(f"Animating {s['shot_id']} with Wan 2.2 ({n + 1}/{total}, a few minutes each)",
                         100 * n / total)
            client = client or Comfy()
            uploaded = client.upload_image(ep.abs(s["raw"]))
            seed = new_seed()
            saved, meta = run_template("video_workflow", {
                "IMAGE": uploaded, "PROMPT": f"{s['motion_prompt']}. {MOTION_SUFFIX}", "SEED": seed,
                "WIDTH": cfg["video_width"], "HEIGHT": cfg["video_height"], "FRAMES": cfg["video_frames"],
                "FPS": cfg["video_fps"], "FILENAME_PREFIX": f"fof/{ep.project_id}/{s['shot_id']}",
            }, ep.path("video", f"{s['shot_id']}-wan-{seed}"), on_progress=ctx.progress, cancelled=ctx.cancelled)
            clip = next((x for x in saved if x.suffix.lower() in (".mp4", ".webm", ".mov")), saved[0])
            s["clip"] = {"path": ep.rel(clip), "kind": "animated", "seed": seed, "model": cfg["video_model_name"],
                         "workflow": meta["workflow"], "digest": digest, "made_at": utc_now(), "ai": True}
        else:
            ctx.progress(f"Making camera move for {s['shot_id']} ({n + 1}/{total})", 100 * n / total)
            out = ep.path("video", f"{s['shot_id']}-move.mp4")
            tl = Timeline([], width=int(vid["width"]), height=int(vid["height"]), fps=int(vid["fps"]))
            seg = Segment(ep.abs(s["image"]), float(s["seconds"]), camera=s["camera"], label=s["shot_id"])
            from .. import media
            _render_segment(tl, seg, out, media.encoder("libx264"))
            # the still already carries its "AI illustration" stamp, so no second label at render
            s["clip"] = {"path": ep.rel(out), "kind": "camera_move", "digest": digest, "made_at": utc_now(),
                         "ai": False, "ai_image": s["type"] == "ai_image"}
        s["approved"] = False
        save_plan(ep, p)
    ctx.progress("All clips made. Watch each one and approve or redo.", 100)


def check(ep: Episode) -> list[Check]:
    p = load_plan(ep)
    if not p["shots"]:
        return [Check(BLOCK, "No clips yet.")]
    missing = [s["shot_id"] for s in p["shots"]
               if not s.get("clip") or s["clip"].get("digest") != _digest(s) or not ep.abs(s["clip"]["path"]).exists()]
    if missing:
        return [Check(BLOCK, f"{len(missing)} clip(s) not made or out of date: {', '.join(missing[:8])}. "
                             "Press Make the clips.")]
    unapproved = [s["shot_id"] for s in p["shots"] if not s.get("approved")]
    if unapproved:
        return [Check(BLOCK, f"{len(unapproved)} clip(s) not approved yet. Watch them and press Approve clip "
                             "(or Approve all clips).")]
    return [Check(OK, f"All {len(p['shots'])} clips made and approved.")]
