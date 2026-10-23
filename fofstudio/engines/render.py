"""The render engine: OwlBox's engine rewritten in Python and extended.

What it does:
  * still images get a slow camera move (zoom, pan, dolly) - the "Ken Burns" look
  * video clips (from Wan) are fitted to the frame, gently slowed or looped to length
  * real cross-fades between shots (any ffmpeg xfade transition)
  * narration placed exactly where each scene starts
  * a music bed looped under everything and ducked whenever the narrator speaks
  * an "AI illustration" label over AI clips, subtitles as .srt and optionally burned in
  * NVENC on the RTX 3060 when it works, libx264 otherwise

Each shot is rendered to its own small file first, so a failure names the shot
that caused it, then everything is joined in one pass.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import media
from ..util import StageError, run

CAMERA_MOVES = ["static", "zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "dolly_in"]

TRANSITIONS = {
    "cut": "fade", "fade": "fade", "crossfade": "fade", "dissolve": "dissolve",
    "fade_to_black": "fadeblack", "fade_to_white": "fadewhite", "wipe_left": "wipeleft",
    "wipe_right": "wiperight", "wipe_up": "wipeup", "wipe_down": "wipedown",
    "slide_left": "slideleft", "slide_right": "slideright", "zoom_blur": "zoomin",
    "circle_open": "circleopen", "circle_close": "circleclose", "pixelize": "pixelize",
    "smooth_left": "smoothleft", "smooth_right": "smoothright",
}


@dataclass
class Segment:
    path: Path
    seconds: float
    kind: str = "image"            # image | clip
    camera: str = "zoom_in"
    transition: str = "fade"       # transition INTO the next segment
    transition_seconds: float = 0.5
    overlay: Path | None = None    # transparent PNG laid over the segment (AI label on clips)
    label: str = ""
    inpoint: float = 0.0           # start this many seconds into a clip
    start: float = 0.0             # filled in by layout()


@dataclass
class AudioCue:
    path: Path
    start: float


@dataclass
class Timeline:
    segments: list[Segment]
    narration: list[AudioCue] = field(default_factory=list)
    music: Path | None = None
    music_volume: float = 0.18
    duck: bool = True
    width: int = 1920
    height: int = 1080
    fps: int = 30
    total: float = 0.0
    # Owlbert in the corner: an ffconcat list of transparent drawings, and when he's visible
    presenter: Path | None = None
    presenter_ranges: list[tuple[float, float]] = field(default_factory=list)
    presenter_corner: str = "bottom_right"

    def layout(self) -> "Timeline":
        """Work out when each segment starts. Segment n+1 starts as segment n begins to fade."""
        if not self.segments:
            raise StageError("Nothing to render: the timeline has no shots.")
        t = 0.0
        for i, seg in enumerate(self.segments):
            if seg.camera not in CAMERA_MOVES:
                seg.camera = "zoom_in"
            if seg.transition not in TRANSITIONS:
                raise StageError(f"Unknown transition '{seg.transition}'.")
            last = i == len(self.segments) - 1
            if last:
                seg.transition_seconds = 0.0
            elif seg.transition == "cut":
                seg.transition_seconds = 1.0 / self.fps
            nxt = None if last else self.segments[i + 1].seconds
            limit = 0.45 * min(seg.seconds, nxt) if nxt else 0
            seg.transition_seconds = max(0.0, min(seg.transition_seconds, limit))
            if not last and seg.transition_seconds <= 0:
                seg.transition_seconds = 1.0 / self.fps
            seg.start = t
            t += seg.seconds - seg.transition_seconds
        self.total = self.segments[-1].start + self.segments[-1].seconds
        return self


def _cover(w: int, h: int) -> str:
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"


def camera_filter(move: str, w: int, h: int, fps: int, frames: int) -> str:
    if move == "static" or frames <= 1:
        return f"{_cover(w, h)},format=yuv420p"
    p = f"(on/{frames - 1})"
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    zoom, x, y = "1", cx, cy
    if move == "zoom_in":
        zoom = f"1+0.18*{p}"
    elif move == "zoom_out":
        zoom = f"1.18-0.18*{p}"
    elif move == "dolly_in":
        zoom, y = f"1+0.22*{p}", f"{cy}-(ih*0.03*{p})"
    elif move == "pan_left":
        zoom, x = "1.15", f"(iw-iw/zoom)*(1-{p})"
    elif move == "pan_right":
        zoom, x = "1.15", f"(iw-iw/zoom)*{p}"
    elif move == "pan_up":
        zoom, y = "1.15", f"(ih-ih/zoom)*(1-{p})"
    elif move == "pan_down":
        zoom, y = "1.15", f"(ih-ih/zoom)*{p}"
    return (f"{_cover(w * 2, h * 2)},zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s={w}x{h}:fps={fps},"
            "format=yuv420p")


def escape_filter_path(path: Path) -> str:
    text = str(Path(path).resolve()).replace("\\", "/")
    return text.replace(":", "\\:").replace("'", "\\'")


def _render_segment(tl: Timeline, seg: Segment, out: Path, enc: dict) -> None:
    frames = max(1, round(seg.seconds * tl.fps))
    w, h, fps = tl.width, tl.height, tl.fps
    args = [media.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error"]
    if seg.kind == "clip":
        clip_len = media.duration(seg.path)
        stretch = min(max(seg.seconds / max(clip_len, 0.1), 1.0), 1.6)
        if seg.inpoint:
            args += ["-ss", f"{seg.inpoint:.3f}"]
        args += ["-stream_loop", "-1", "-i", str(seg.path)]
        chain = f"[0:v]setpts={stretch:.4f}*PTS,fps={fps},{_cover(w, h)},format=yuv420p"
    else:
        args += ["-loop", "1", "-framerate", str(fps), "-t", f"{seg.seconds:.3f}", "-i", str(seg.path)]
        chain = f"[0:v]{camera_filter(seg.camera, w, h, fps, frames)}"
    if seg.overlay:
        args += ["-i", str(seg.overlay)]
        chain += f"[base];[1:v]scale={w}:{h}[ov];[base][ov]overlay=0:0:format=auto,format=yuv420p"
    args += ["-filter_complex", chain + "[v]", "-map", "[v]", "-frames:v", str(frames),
             "-c:v", enc["name"], *enc["final"], "-pix_fmt", "yuv420p", "-r", str(fps), "-an", str(out)]
    run(args, label=f"rendering {seg.label or seg.path.name}", timeout=1800)


def render(tl: Timeline, out: Path, srt: Path | None = None, burn_subs: bool = False,
           encoder: str = "auto", on_progress: Callable[[str], None] | None = None,
           cancelled: Callable[[], bool] | None = None, keep_temp: bool = False) -> dict:
    tl.layout()
    enc = media.encoder(encoder)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="fof-render-"))
    try:
        seg_files = []
        for i, seg in enumerate(tl.segments):
            if cancelled and cancelled():
                raise StageError("Cancelled.")
            if on_progress:
                on_progress(f"Rendering shot {i + 1}/{len(tl.segments)} ({seg.label})")
            f = work / f"seg-{i:04d}.mp4"
            _render_segment(tl, seg, f, enc)
            seg_files.append(f)

        if on_progress:
            on_progress("Joining shots, mixing narration and music")
        args = [media.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error"]
        for f in seg_files:
            args += ["-i", str(f)]
        n = len(seg_files)
        for cue in tl.narration:
            args += ["-i", str(cue.path)]
        if tl.music:
            args += ["-stream_loop", "-1", "-i", str(tl.music)]
        owl_in = None
        if tl.presenter and tl.presenter_ranges:
            owl_in = n + len(tl.narration) + (1 if tl.music else 0)
            args += ["-f", "concat", "-safe", "0", "-i", str(tl.presenter)]

        steps: list[str] = []
        v = "0:v"
        for i in range(1, n):
            prev = tl.segments[i - 1]
            offset = tl.segments[i].start
            steps.append(f"[{v}][{i}:v]xfade=transition={TRANSITIONS[prev.transition]}:"
                         f"duration={prev.transition_seconds:.3f}:offset={offset:.3f}[vx{i}]")
            v = f"vx{i}"
        if owl_in is not None:
            margin_x, margin_y = int(tl.width * 0.025), int(tl.height * 0.04)
            x = f"W-w-{margin_x}" if "right" in tl.presenter_corner else str(margin_x)
            y = f"H-h-{margin_y}" if "bottom" in tl.presenter_corner else str(margin_y)
            when = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in tl.presenter_ranges)
            steps.append(f"[{owl_in}:v]fps={tl.fps},format=rgba[owl]")
            steps.append(f"[{v}][owl]overlay=x={x}:y={y}:enable='{when}':eof_action=pass:format=auto,"
                         f"format=yuv420p[vowl]")
            v = "vowl"
        if burn_subs and srt:
            steps.append(f"[{v}]subtitles='{escape_filter_path(srt)}':force_style='FontName=Arial,"
                         "FontSize=22,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
                         "BorderStyle=1,Outline=2,Shadow=0,MarginV=48'[vsub]")
            v = "vsub"

        a = None
        total = f"{tl.total:.3f}"
        if tl.narration:
            labels = []
            for k, cue in enumerate(tl.narration):
                lab = f"n{k}"
                steps.append(f"[{n + k}:a]aformat=sample_fmts=fltp:sample_rates=48000:"
                             f"channel_layouts=stereo,adelay={round(cue.start * 1000)}:all=1[{lab}]")
                labels.append(f"[{lab}]")
            steps.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0,"
                         f"apad,atrim=0:{total}[narr]")
            a = "narr"
        if tl.music:
            m_in = n + len(tl.narration)
            steps.append(f"[{m_in}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                         f"atrim=0:{total},volume={tl.music_volume},"
                         f"afade=t=in:d=2,afade=t=out:st={max(0.0, tl.total - 4):.3f}:d=4[mus]")
            if a and tl.duck:
                steps.append("[narr]asplit=2[narr1][key]")
                steps.append("[mus][key]sidechaincompress=threshold=0.02:ratio=10:attack=15:"
                             "release=600:makeup=1[ducked]")
                steps.append("[narr1][ducked]amix=inputs=2:duration=first:normalize=0[mix]")
                a = "mix"
            elif a:
                steps.append(f"[{a}][mus]amix=inputs=2:duration=first:normalize=0[mix]")
                a = "mix"
            else:
                a = "mus"

        if steps:
            args += ["-filter_complex", ";".join(steps)]
        args += ["-map", "0:v" if v == "0:v" else f"[{v}]"]
        if a:
            args += ["-map", f"[{a}]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
        args += ["-t", total, "-c:v", enc["name"], *enc["final"], "-pix_fmt", "yuv420p",
                 "-r", str(tl.fps), "-movflags", "+faststart", str(out)]
        run(args, label="joining the video", timeout=7200)
    finally:
        if keep_temp:
            if on_progress:
                on_progress(f"Working files kept in {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    return {"output": str(out), "seconds": media.duration(out), "encoder": enc["name"],
            "has_audio": media.has_audio(out)}
