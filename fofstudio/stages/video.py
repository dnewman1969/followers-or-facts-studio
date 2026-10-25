"""Video: turn every picked picture into a moving clip.

Step 1, "Write scene instructions" (video_plan): for each picture the local AI writes how
the shot plays out in plain words, the motion prompt for the animation model, the camera
move, how long it lasts, and HOW it will be made:
    animate        Wan 2.2 image-to-video in ComfyUI (about 5-6 minutes per clip on the 3060). The picture
                   is the first frame, so Owlbert and caricatures stay exactly as drawn.
    text_to_video  Wan 2.2 TI2V-5B makes the clip from the words alone: for b-roll with no particular
                   character (crowds, places, weather, metaphors). About 5-10 minutes per clip.
    camera_move    a smooth zoom or pan over the still (drawn frame by frame, no jitter), in seconds
You can edit any of it. Step 2, "Make the clips" (video), makes every clip.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..comfy import Comfy, new_seed, run_template
from ..config import settings
from ..engines.render import CAMERA_MOVES, Segment, Timeline, _render_segment
from ..episode import Episode
from ..llm import Ollama
from ..util import StageError, read_json, sha256_text, utc_now, write_json
from .base import BLOCK, OK, Check, Context
from .storyboard import shots as board_shots

MOTION_SUFFIX = "slow, subtle cinematic motion, steady camera, natural movement, no sudden changes"
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "how_it_plays": {"type": "string"},
        "motion_prompt": {"type": "string"},
        "camera": {"type": "string", "enum": CAMERA_MOVES},
    },
    "required": ["how_it_plays", "motion_prompt", "camera"],
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
    sb = settings()["storyboard"]
    t2v_per_scene = int(sb.get("t2v_shots_per_scene", 0))
    animate_ids = choose_animated(ep, shots, ctx.options.get("level") or sb.get("animation_level", "balanced"))
    from .. import styles
    style = styles.get(ep.creative()["style"])
    animated: dict[str, int] = {}
    t2v: dict[str, int] = {}
    out = []
    llm = Ollama(job="storyboard")
    for n, shot in enumerate(shots):
        ctx.check_cancel()
        prev = old.get(shot["shot_id"])
        if prev and prev["image"] == shot["image"]["path"] and not ctx.options.get("redo_all"):
            out.append(prev)
            continue
        seconds = float(shot.get("seconds") or style.shot_seconds)
        if shot["type"] == "ai_image":
            ctx.progress(f"Writing instructions for {shot['shot_id']} ({n + 1}/{len(shots)})",
                         100 * n / len(shots))
            p = llm.chat_json([
                {"role": "system", "content": (
                    f"You direct short shots for a {style.name} video, made from a still picture. Describe how "
                    "the shot plays out in one or two plain sentences, then write a motion prompt for an "
                    f"image-to-video model (what moves and how, in this style: {style.motion}; keep characters "
                    "exactly as drawn; never add people, text or logos), and pick a camera move.")},
                {"role": "user", "content": f"Picture: {shot['prompt']}\nShot length: {seconds:.1f} seconds"},
            ], PLAN_SCHEMA, temperature=0.5)
            kind = shot.get("kind", "broll")
            sid = shot["scene_id"]
            # the animation level picks which shots Wan animates; b-roll can be text-to-video; everything
            # else moves in 2.5D (parallax) so nothing is a flat zoom on a still
            if shot["shot_id"] in animate_ids:
                method = "animate"
            elif kind == "broll" and t2v.get(sid, 0) < t2v_per_scene:
                method = "text_to_video"
            else:
                method = "parallax" if sb.get("parallax", True) else "camera_move"
            animated[sid] = animated.get(sid, 0) + (method == "animate")
            t2v[sid] = t2v.get(sid, 0) + (method == "text_to_video")
            entry = {"how_it_plays": p["how_it_plays"], "motion_prompt": p["motion_prompt"],
                     "camera": p["camera"] if p["camera"] in CAMERA_MOVES else "zoom_in",
                     "seconds": max(2.0, min(10.0, seconds)), "method": method, "kind": kind}
        else:
            entry = {"how_it_plays": f"{shot['type'].replace('_', ' ')} holds on screen: \"{shot.get('text', '')[:80]}\"",
                     "motion_prompt": "", "camera": "zoom_in" if shot["type"] != "title_card" else "static",
                     "seconds": seconds, "method": "camera_move", "kind": "card"}
        if shot.get("owl_live"):   # the empty set moves; Owlbert is laid on top, talking, when rendering
            from .storyboard import set_only
            entry["motion_prompt"] = set_only(entry["motion_prompt"]) + ". The set stays empty."
            entry["owl_live"] = shot["owl_live"]
        out.append({"shot_id": shot["shot_id"], "scene_id": shot["scene_id"], "type": shot["type"],
                    "image": shot["image"]["path"], "raw": shot["image"].get("raw"),
                    "prompt": shot.get("prompt", ""), **entry, "clip": None, "approved": False})
    save_plan(ep, {"shots": out, "made_at": utc_now()})
    ctx.progress("Scene instructions written. Read them, change anything, then make the clips.", 100)


LEVELS = {"fast": 0.1, "balanced": 0.34, "full": 1.0}
MINUTES_PER_CLIP = 6.0     # Wan 2.2 14B + Lightning, ~5 s at 480p, on an RTX 3060 12 GB


def choose_animated(ep: Episode, shots: list[dict[str, Any]], level: str) -> set[str]:
    """Which pictures Wan animates, for the chosen level: spread evenly through the video, illustrative
    shots first. Never evidence cards, never Owlbert's empty sets (he's animated live on top already),
    and not harm scenes in a careful topic (no vivid recreations of what happened to real people)."""
    share = LEVELS.get(level, LEVELS["balanced"])
    script_roles = {}
    try:
        from .script import load as load_script
        script_roles = {sc["scene_id"]: sc.get("role", "") for sc in load_script(ep)["scenes"]}
    except Exception:  # noqa: BLE001 - no script: every scene is fine
        pass
    careful = ep.creative().get("careful")
    pool = [s for s in shots if s["type"] == "ai_image" and not s.get("owl_live")
            and not (careful and script_roles.get(s["scene_id"]) == "harm")]
    want = len(pool) if share >= 1 else max(1 if pool else 0, round(share * len(pool)))
    if want >= len(pool):
        return {s["shot_id"] for s in pool}
    # caricatures first (they need motion to read as cartoons), then every k-th shot so they're spread out
    chosen = [s["shot_id"] for s in pool if s.get("kind") == "caricature"][:want]
    step = len(pool) / max(1, want - len(chosen)) if want > len(chosen) else 0
    k = step / 2
    while len(chosen) < want and step:
        sid = pool[min(len(pool) - 1, int(k))]["shot_id"]
        if sid not in chosen:
            chosen.append(sid)
        k += step
        if k >= len(pool):
            k = (k % len(pool)) + 0.5
            if all(s["shot_id"] in chosen for s in pool):
                break
    return set(chosen)


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
    t = sum(1 for s in p["shots"] if s["method"] == "text_to_video")
    px = sum(1 for s in p["shots"] if s["method"] == "parallax")
    gpu = n * MINUTES_PER_CLIP + t * 8
    return [Check(OK, f"{len(p['shots'])} shots planned: {n} animated by Wan, {t} made from words, {px} moving in 2.5D "
                      f"(depth), the rest cards. About {gpu / 60:.1f} hours of GPU time"
                      + (" - good for an overnight run." if gpu > 180 else "."))]


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
        if s["method"] == "text_to_video":
            ctx.progress(f"Making {s['shot_id']} from words with Wan 2.2 ({n + 1}/{total}, several minutes each)",
                         100 * n / total)
            seed = new_seed()
            t2v = settings()["comfyui"]
            saved, meta = run_template("t2v_workflow", {
                "PROMPT": f"{s['prompt']}. {s['motion_prompt']}. {MOTION_SUFFIX}", "SEED": seed,
                "WIDTH": t2v.get("t2v_width", 1280), "HEIGHT": t2v.get("t2v_height", 704),
                "FRAMES": t2v.get("t2v_frames", 121), "FPS": t2v.get("t2v_fps", 24),
                "FILENAME_PREFIX": f"fof/{ep.project_id}/{s['shot_id']}-t2v",
            }, ep.path("video", f"{s['shot_id']}-t2v-{seed}"), cancelled=ctx.cancelled,
                on_progress=lambda t, p=None, sid=s["shot_id"], k=n: ctx.progress(
                    f"Making {sid} from words ({k + 1}/{total}): {t}"))
            clip = next((x for x in saved if x.suffix.lower() in (".mp4", ".webm", ".mov")), saved[0])
            s["clip"] = {"path": ep.rel(clip), "kind": "text_to_video", "seed": seed,
                         "model": t2v.get("t2v_model_name", "Wan 2.2 TI2V-5B"), "workflow": meta["workflow"],
                         "digest": digest, "made_at": utc_now(), "ai": True}
        elif s["method"] == "animate":
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
            }, ep.path("video", f"{s['shot_id']}-wan-{seed}"), cancelled=ctx.cancelled,
                on_progress=lambda t, p=None, sid=s["shot_id"], k=n: ctx.progress(
                    f"Animating {sid} with Wan 2.2 ({k + 1}/{total}): {t}"))
            clip = next((x for x in saved if x.suffix.lower() in (".mp4", ".webm", ".mov")), saved[0])
            s["clip"] = {"path": ep.rel(clip), "kind": "animated", "seed": seed, "model": cfg["video_model_name"],
                         "workflow": meta["workflow"], "digest": digest, "made_at": utc_now(), "ai": True}
        elif s["method"] == "parallax":
            ctx.progress(f"Making a 2.5D move for {s['shot_id']} ({n + 1}/{total})", 100 * n / total)
            depth = depth_map(ep, s, ctx)
            out = ep.path("video", f"{s['shot_id']}-parallax.mp4")
            tl = Timeline([], width=int(vid["width"]), height=int(vid["height"]), fps=int(vid["fps"]))
            seg = Segment(ep.abs(s["image"]), float(s["seconds"]), camera=s["camera"], label=s["shot_id"],
                          depth=ep.abs(depth) if depth else Path("estimated"))
            from .. import media
            _render_segment(tl, seg, out, media.encoder("libx264"))
            s["clip"] = {"path": ep.rel(out), "kind": "parallax", "digest": digest, "made_at": utc_now(),
                         "ai": False, "ai_image": True, "still": s["image"], "camera": s["camera"],
                         "depth": depth or "estimated"}
        else:
            ctx.progress(f"Making camera move for {s['shot_id']} ({n + 1}/{total})", 100 * n / total)
            out = ep.path("video", f"{s['shot_id']}-move.mp4")
            tl = Timeline([], width=int(vid["width"]), height=int(vid["height"]), fps=int(vid["fps"]))
            seg = Segment(ep.abs(s["image"]), float(s["seconds"]), camera=s["camera"], label=s["shot_id"])
            from .. import media
            _render_segment(tl, seg, out, media.encoder("libx264"))
            # the still already carries its "AI illustration" stamp, so no second label at render
            s["clip"] = {"path": ep.rel(out), "kind": "camera_move", "digest": digest, "made_at": utc_now(),
                         "ai": False, "ai_image": s["type"] == "ai_image",
                         "still": s["image"], "camera": s["camera"]}
        s["approved"] = False
        save_plan(ep, p)
    ctx.progress("All clips made. Watch each one and approve or redo.", 100)


_DEPTH_NODE: dict[str, bool] = {}


def depth_map(ep: Episode, s: dict[str, Any], ctx: Context) -> str | None:
    """A depth picture for the 2.5D move, made in ComfyUI by Depth Anything V2 Small (Apache-2.0) if the
    comfyui_controlnet_aux nodes are installed; otherwise None and the render estimates depth itself."""
    out = ep.path("video", f"{s['shot_id']}-depth.png")
    if out.exists():
        return ep.rel(out)
    url = settings()["comfyui"]["url"]
    if url not in _DEPTH_NODE:
        try:
            _DEPTH_NODE[url] = Comfy().has_node("DepthAnythingV2Preprocessor")
        except Exception:  # noqa: BLE001 - ComfyUI not running: estimate instead
            _DEPTH_NODE[url] = False
        if not _DEPTH_NODE[url]:
            ctx.log("2.5D moves use estimated depth. For better depth, install the free comfyui_controlnet_aux nodes "
                    "in ComfyUI (Manager → search 'controlnet aux'); docs/MODELS.md.")
    if not _DEPTH_NODE[url] or not s.get("raw"):
        return None
    try:
        client = Comfy()
        uploaded = client.upload_image(ep.abs(s["raw"]))
        saved, _ = run_template("depth_workflow", {"IMAGE": uploaded, "FILENAME_PREFIX": f"fof/{ep.project_id}/depth"},
                                ep.path("video", f"{s['shot_id']}-depth-raw"), cancelled=ctx.cancelled)
        from PIL import Image
        Image.open(saved[0]).convert("L").save(out)
        return ep.rel(out)
    except Exception as exc:  # noqa: BLE001 - fall back to estimated depth rather than fail the shot
        ctx.log(f"{s['shot_id']}: depth model failed ({exc}); using estimated depth.")
        return None


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
