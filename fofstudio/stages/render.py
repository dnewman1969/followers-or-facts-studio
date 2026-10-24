"""Render: turn the Production timeline into the finished YouTube video (or a fast preview).

Options: {"draft": true} makes a quick 640x360 preview (render/preview.mp4) for the
Production page's player; otherwise it renders the full 1080p file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import bits, cards, media, owl
from ..config import settings
from ..engines.render import AudioCue, Effect, MusicCue, Segment, Timeline, render
from ..episode import Episode
from ..util import StageError, read_json, utc_now, write_json, write_text
from . import production
from .base import BLOCK, OK, WARN, Check, Context
from .captions import build_srt


def _black(ep: Episode, w: int, h: int) -> Path:
    p = ep.path("render", f"black-{w}x{h}.png")
    if not p.exists():
        from PIL import Image
        p.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (w, h), (0, 0, 0)).save(p)
    return p


def build(ep: Episode, w: int, h: int, fps: int, progress=lambda t, p=None: None
          ) -> tuple[Timeline, dict[str, float], list[dict[str, Any]]]:
    tl_json = production.load(ep)
    if not tl_json:
        raise StageError("Assemble the timeline on the Production page first.")
    label_png = cards.label_overlay(w, h, ep.path("render", f"ai-label-{w}.png"))
    video = sorted(tl_json["video"], key=lambda c: c["start"])
    segments: list[Segment] = []
    t = 0.0
    for i, c in enumerate(video):
        if c["start"] > t + 0.05:   # a gap on the video track becomes black
            segments.append(Segment(_black(ep, w, h), c["start"] - t, kind="image", camera="static",
                                    transition="cut", transition_seconds=0, label="black"))
            t = c["start"]
        nxt = video[i + 1] if i + 1 < len(video) else None
        overlap = max(0.0, (c["start"] + c["duration"]) - nxt["start"]) if nxt else 0.0
        if c.get("still") and ep.abs(c["still"]).exists():   # a camera move, redrawn at exactly this length
            depth = c.get("depth")
            segments.append(Segment(ep.abs(c["still"]), c["duration"], kind="image", camera=c.get("camera", "zoom_in"),
                                    transition="fade" if overlap > 0.05 else "cut",
                                    transition_seconds=min(overlap, c["duration"] * 0.45), label=c["label"],
                                    depth=None if not depth else Path("estimated") if depth == "estimated"
                                    else ep.abs(depth)))
            t = c["start"] + c["duration"] - overlap
            continue
        segments.append(Segment(ep.abs(c["src"]), c["duration"], kind="clip", inpoint=c.get("inpoint", 0.0),
                                overlay=label_png if c.get("ai") else None,
                                transition="fade" if overlap > 0.05 else "cut",
                                transition_seconds=min(overlap, c["duration"] * 0.45), label=c["label"]))
        t = c["start"] + c["duration"] - overlap
    cues = [AudioCue(ep.abs(s["src"]), s["start"]) for s in tl_json.get("speech", [])]
    music = tl_json.get("music") or []
    mix = production.mix(tl_json)
    snd = settings()["sound"]
    clip_gain = float(music[0].get("volume", 1.0)) if music else 1.0
    if abs(clip_gain - 0.18) < 1e-6:  # timelines from v0.3 and earlier stored the old fixed music level here
        clip_gain = 1.0
    cued = any("fade_in" in m for m in music)   # v0.4.4+: one piece of music per mood, from the script
    music_cues = [MusicCue(ep.abs(m["src"]), m["start"], m["duration"], float(m.get("inpoint", 0.0)),
                           float(m.get("fade_in", 1.5)), float(m.get("fade_out", 2.0)), float(m.get("volume", 1.0)))
                  for m in music if ep.abs(m["src"]).exists()] if cued else []
    effects = [Effect(ep.abs(x["src"]), x["start"], float(x.get("volume", 0.5)))
               for x in tl_json.get("sfx", []) if ep.abs(x["src"]).exists()]
    tl = Timeline(segments, cues, music=ep.abs(music[0]["src"]) if music and not cued else None,
                  music_cues=music_cues, effects=effects,
                  music_volume=(1.0 if cued else clip_gain) * 10 ** (mix["music_db"] / 20),
                  duck=bool(settings()["video"]["duck_music"]), width=w, height=h, fps=fps,
                  speech_db=mix["speech_db"], master_db=mix["master_db"],
                  loudness_lufs=float(snd["loudness_lufs"]) if snd["normalize_loudness"] else None)
    ocfg = settings()["owl"]
    if tl_json.get("owl") and ocfg["presenter"]:
        tl.layout()
        speech = [(s["start"], ep.abs(s["src"]), s.get("text")) for s in tl_json["speech"]]
        tl.presenter = owl.presenter_track(speech, tl.total, ep.path("render", f"owl-{h}"),
                                           height=int(h * float(ocfg["presenter_height"])), fps=fps,
                                           progress=progress)
        ranges = bits.merge([(o["start"], o["start"] + o["duration"]) for o in tl_json["owl"]])
        # only one Owlbert at a time: the corner one steps aside while a shot shows him
        ranges = bits.subtract(ranges, production.owl_shot_ranges(tl_json))
        moves = tl_json.get("moves") or []
        if moves and ocfg.get("moves", True):
            tl.moves, tl.moves_ranges = bits.render_track(moves, speech, tl.total, ep.path("render", f"moves-{h}"),
                                                          w, h, fps, progress)
            ranges = bits.subtract(ranges, tl.moves_ranges)   # he can't be in the corner while he's flying
        # Owlbert big on the painted set, talking: the same puppet at the size of the set (the set stays empty
        # while a move plays, so there's still only one of him)
        live = [(a, b, c["owl_live"]) for c in video if c.get("owl_live")
                for a, b in bits.subtract([(c["start"], c["start"] + c["duration"])], tl.moves_ranges)]
        if live:
            tl.stage_owl = owl.presenter_track(speech, tl.total, ep.path("render", f"owl-stage-{h}"),
                                               height=int(h * 0.66), fps=fps, progress=progress)
            tl.stage_owl_spots = live
        tl.presenter_ranges = ranges
        tl.presenter_corner = ocfg["presenter_corner"]
    starts = {s["scene_id"]: s["start"] for s in tl_json.get("speech", [])}
    chapters = [{"scene_id": c["scene_id"], "start": round(c["start"], 2)} for c in video
                if c["scene_id"] not in {x["scene_id"] for x in video[:video.index(c)]}]
    return tl, starts, chapters


def run(ctx: Context) -> None:
    ep = ctx.episode
    cfg = settings()["video"]
    draft = bool(ctx.options.get("draft"))
    w, h, fps = (854, 480, 24) if draft else (int(cfg["width"]), int(cfg["height"]), int(cfg["fps"]))
    ctx.progress("Getting the timeline ready", 2)
    tl, starts, chapters = build(ep, w, h, fps, ctx.progress)
    name = "preview" if draft else ep.project_id
    timings = read_json(ep.path("captions", "words.json"), {}) or {}
    srt_path = ep.path("render", f"{name}.srt")
    write_text(srt_path, build_srt(starts, timings, lead=0.0))
    out = ep.path("render", f"{name}.mp4")
    n = len(tl.segments)

    def prog(text: str, pct: float | None = None) -> None:
        if pct is None and text.startswith("Rendering shot "):
            try:
                k = int(text.split()[2].split("/")[0])
                pct = 5 + 80 * k / max(1, n)
            except (ValueError, IndexError):
                pct = None
        elif pct is None and text.startswith("Joining"):
            pct = 88
        ctx.progress(text, pct)

    result = render(tl, out, srt=srt_path, burn_subs=bool(settings()["captions"]["burn_in"]) and not draft,
                    encoder="libx264" if draft else cfg["encoder"], on_progress=prog, cancelled=ctx.cancelled)
    info = {"draft": draft, "output": ep.rel(out), "srt": ep.rel(srt_path), "seconds": result["seconds"],
            "encoder": result["encoder"], "chapters": chapters, "made_at": utc_now(),
            "timeline_saved_at": production.load(ep).get("saved_at")}
    write_json(ep.path("render", "preview.json" if draft else "timeline.json"), info)
    ctx.progress(f"{'Preview' if draft else 'Video'} ready: {result['seconds'] / 60:.1f} min", 100)


def check(ep: Episode) -> list[Check]:
    info = read_json(ep.path("render", "timeline.json"))
    if not info:
        return [Check(BLOCK, "The full video hasn't been rendered yet. Press Render final video.")]
    out = ep.abs(info["output"])
    if not out.exists():
        return [Check(BLOCK, "The rendered file is missing. Render again.")]
    checks = []
    try:
        if not media.has_audio(out):
            checks.append(Check(BLOCK, "The video has no sound."))
    except StageError as exc:
        checks.append(Check(BLOCK, str(exc)))
    if info.get("timeline_saved_at") != production.load(ep).get("saved_at"):
        checks.append(Check(BLOCK, "You changed the timeline after this render. Render again."))
    target = float(ep.creative().get("minutes", 0) or 0)
    if target and info["seconds"] < target * 60 * 0.95:
        checks.append(Check(WARN, f"The video is {info['seconds'] / 60:.1f} minutes; you asked for {target:g}. "
                                  "The length comes from the script: on the Script page press Make it longer, "
                                  "then redo the speech track."))
    checks.append(Check(OK, f"{info['seconds'] / 60:.1f} min video (in the folder that just opened). "
                            "Watch all of it before approving."))
    return checks
