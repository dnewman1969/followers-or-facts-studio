"""Stage 9 - Render: assemble shots, narration, music and captions into the final MP4.

Pass {"draft": true} for a quick 720p preview.
"""

from __future__ import annotations

from typing import Any

from .. import cards, media
from ..config import settings
from ..engines.render import AudioCue, Segment, Timeline, render
from ..episode import Episode
from ..util import StageError, read_json, utc_now, write_json, write_text
from .base import BLOCK, OK, WARN, Check, Context
from .captions import build_srt
from .script import load as load_script

LEAD = 0.35            # narration starts this long after its scene appears
WITHIN_SCENE_FADE = 0.4
MIN_SHOT = 1.8


def _skipped(ep: Episode, stage: str) -> bool:
    st = ep.stage_status(stage)
    return st["status"] != "approved" or (st.get("note") or "").startswith("SKIPPED")


def build_timeline(ep: Episode, width: int, height: int, fps: int,
                   log=lambda m: None) -> tuple[Timeline, dict[str, float], list[dict[str, Any]]]:
    cfg = settings()["video"]
    script = load_script(ep)
    narration = read_json(ep.path("audio", "narration.json"), {}) or {}
    board = ep.storyboard()
    use_clips = not _skipped(ep, "video")
    tail = float(settings()["voice"]["tail_seconds"])
    scene_fade = float(cfg["transition_seconds"])
    label_png = None

    segments: list[Segment] = []
    cues: list[AudioCue] = []
    starts: dict[str, float] = {}
    chapters: list[dict[str, Any]] = []
    t = 0.0
    scene_ids = [s["scene_id"] for s in script["scenes"]] + ["CREDITS"]
    by_scene: dict[str, list[dict[str, Any]]] = {}
    for shot in board.get("shots", []):
        by_scene.setdefault(shot["scene_id"], []).append(shot)

    for sc_id in scene_ids:
        shots = [s for s in by_scene.get(sc_id, []) if s.get("image")]
        if not shots:
            continue
        m = narration.get(sc_id)
        if m:
            scene_len = LEAD + m["seconds"] + tail
            cues.append(AudioCue(ep.abs(m["path"]), t + LEAD))
        else:
            scene_len = float(shots[0].get("seconds") or 6)
        keep = max(1, int(scene_len // MIN_SHOT))
        if len(shots) > keep:
            log(f"{sc_id}: only {scene_len:.1f}s long, so showing {keep} of {len(shots)} shots.")
            shots = sorted(shots, key=lambda s: -s["weight"])[:keep]
            shots.sort(key=lambda s: s["shot_id"])
        weights = sum(s["weight"] for s in shots)
        starts[sc_id] = t
        chapters.append({"scene_id": sc_id, "start": round(t, 2)})
        for i, shot in enumerate(shots):
            last_in_scene = i == len(shots) - 1
            overlap = scene_fade if last_in_scene else WITHIN_SCENE_FADE
            seconds = scene_len * shot["weight"] / weights + overlap
            clip = shot.get("clip") if use_clips else None
            if clip and ep.abs(clip["path"]).exists():
                if label_png is None:
                    label_png = cards.label_overlay(width, height, ep.path("render", "ai-label.png"))
                seg = Segment(ep.abs(clip["path"]), seconds, kind="clip", overlay=label_png,
                              label=shot["shot_id"])
            else:
                seg = Segment(ep.abs(shot["image"]["path"]), seconds, kind="image",
                              camera=shot.get("camera", "zoom_in"), label=shot["shot_id"])
            seg.transition = cfg["transition"] if last_in_scene else "fade"
            seg.transition_seconds = overlap
            segments.append(seg)
        t += scene_len

    music = None
    if not _skipped(ep, "music"):
        meta = read_json(ep.path("audio", "music", "music.json"))
        if meta and ep.abs(meta["path"]).exists():
            music = ep.abs(meta["path"])
    tl = Timeline(segments, cues, music=music, music_volume=float(cfg["music_volume"]),
                  duck=bool(cfg["duck_music"]), width=width, height=height, fps=fps)
    return tl, starts, chapters


def run(ctx: Context) -> None:
    ep = ctx.episode
    cfg = settings()["video"]
    draft = bool(ctx.options.get("draft"))
    w, h, fps = (1280, 720, 30) if draft else (int(cfg["width"]), int(cfg["height"]), int(cfg["fps"]))
    tl, starts, chapters = build_timeline(ep, w, h, fps, log=ctx.log)
    timings = read_json(ep.path("captions", "words.json"), {}) or {}
    srt_path = ep.path("render", f"{ep.project_id}{'-draft' if draft else ''}.srt")
    write_text(srt_path, build_srt(starts, timings, lead=LEAD))
    out = ep.path("render", f"{ep.project_id}{'-draft' if draft else ''}.mp4")
    result = render(tl, out, srt=srt_path, burn_subs=bool(settings()["captions"]["burn_in"]),
                    encoder="libx264" if draft else cfg["encoder"], on_progress=ctx.progress,
                    cancelled=ctx.cancelled)
    write_json(ep.path("render", "timeline.json"), {
        "draft": draft, "output": ep.rel(out), "srt": ep.rel(srt_path), "seconds": result["seconds"],
        "encoder": result["encoder"], "chapters": chapters, "made_at": utc_now(),
        "shots": [{"label": s.label, "start": round(s.start, 2), "seconds": round(s.seconds, 2),
                   "kind": s.kind} for s in tl.segments],
    })
    ctx.log(f"Rendered {result['seconds'] / 60:.1f} min with {result['encoder']}: {out.name}")


def check(ep: Episode) -> list[Check]:
    info = read_json(ep.path("render", "timeline.json"))
    if not info:
        return [Check(BLOCK, "Not rendered yet.")]
    out = ep.abs(info["output"])
    if not out.exists():
        return [Check(BLOCK, "The rendered file is missing. Render again.")]
    checks = []
    if info.get("draft"):
        checks.append(Check(BLOCK, "This is the 720p draft. Render the full version before approving."))
    try:
        if not media.has_audio(out):
            checks.append(Check(BLOCK, "The video has no sound."))
    except StageError as exc:
        checks.append(Check(BLOCK, str(exc)))
    newest_input = max((p.stat().st_mtime for p in ep.folder.glob("audio/narration/*.wav")), default=0)
    if newest_input > out.stat().st_mtime:
        checks.append(Check(WARN, "Narration changed after this render. Render again."))
    checks.append(Check(OK, f"{info['seconds'] / 60:.1f} min video. Watch all of it before approving."))
    return checks
