"""Stage 5 (optional) - Animate chosen shots with Wan 2.2 image-to-video in ComfyUI.

Only shots marked "animate" in the storyboard are sent (one per scene by
default). Expect about 5-6 minutes per shot on an RTX 3060 with the 4-step
Lightning LoRA, so this is a good overnight job. Shots that aren't animated
get a camera move (zoom/pan) at render time instead, which costs nothing.
Skip this stage to make an all-stills episode.
"""

from __future__ import annotations

from ..comfy import Comfy, new_seed, run_template
from ..config import settings
from ..episode import Episode
from ..util import StageError, utc_now
from .base import BLOCK, OK, WARN, Check, Context

MOTION = ("slow, subtle cinematic camera movement, gentle parallax, natural motion, "
          "documentary b-roll, steady, no sudden changes")


def run(ctx: Context) -> None:
    ep = ctx.episode
    board = ep.storyboard()
    cfg = settings()["comfyui"]
    redo = ctx.options.get("redo") or []
    todo = [s for s in board.get("shots", []) if s.get("animate") and s["type"] == "ai_image"]
    if not todo:
        raise StageError("No shots are marked to animate. Mark some on the Storyboard tab, "
                         "or Skip this stage.")
    client = Comfy()
    for n, shot in enumerate(todo, 1):
        ctx.check_cancel()
        sid = shot["shot_id"]
        if shot.get("clip") and ep.abs(shot["clip"]["path"]).exists() and \
                not (redo == "all" or sid in redo):
            continue
        if not shot.get("image") or not shot["image"].get("raw"):
            raise StageError(f"{sid} has no AI image to animate. Run Images first.")
        ctx.progress(f"Animating {n}/{len(todo)}: {sid} (several minutes each)")
        uploaded = client.upload_image(ep.abs(shot["image"]["raw"]))
        seed = new_seed()
        saved, meta = run_template("video_workflow", {
            "IMAGE": uploaded, "PROMPT": f"{shot['prompt']}. {MOTION}", "SEED": seed,
            "WIDTH": cfg["video_width"], "HEIGHT": cfg["video_height"],
            "FRAMES": cfg["video_frames"], "FPS": cfg["video_fps"],
            "FILENAME_PREFIX": f"fof/{ep.project_id}/{sid}",
        }, ep.path("video", f"{sid}-{seed}"), on_progress=ctx.progress, cancelled=ctx.cancelled)
        clip = next((p for p in saved if p.suffix.lower() in (".mp4", ".webm", ".mov", ".webp", ".gif")),
                    saved[0])
        shot["clip"] = {"path": ep.rel(clip), "seed": seed, "model": cfg["video_model_name"],
                        "workflow": meta["workflow"], "licence": "Apache-2.0 model; output ours",
                        "made_at": utc_now()}
        ep.save_storyboard(board)


def check(ep: Episode) -> list[Check]:
    board = ep.storyboard()
    todo = [s for s in board.get("shots", []) if s.get("animate") and s["type"] == "ai_image"]
    if not todo:
        return [Check(WARN, "No shots marked to animate; Skip this stage for an all-stills video.")]
    missing = [s["shot_id"] for s in todo if not s.get("clip") or not ep.abs(s["clip"]["path"]).exists()]
    if missing:
        return [Check(BLOCK, f"{len(missing)} animated shot(s) not made yet: {', '.join(missing)}. "
                             "Run again, un-mark them, or Skip this stage.")]
    return [Check(OK, f"{len(todo)} animated clips ready. Watch them before approving.")]
