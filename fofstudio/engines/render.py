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
    # the mix: speech level, and the whole video's loudness (YouTube plays everything near -14 LUFS)
    speech_db: float = 0.0
    master_db: float = 0.0
    loudness_lufs: float | None = None   # None = don't normalize
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


# RGB pictures -> video the way YouTube expects (BT.709, limited range), so colours aren't washed out
TO_YUV = "scale=out_color_matrix=bt709:out_range=tv:flags=lanczos+accurate_rnd,format=yuv420p"
COLOR_TAGS = ["-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]


def _ease(p: float) -> float:
    """Mostly steady speed, with a gentle start and finish."""
    smooth = p * p * (3 - 2 * p)
    return 0.6 * p + 0.4 * smooth


def kenburns_boxes(move: str, bw: float, bh: float, frames: int) -> list[tuple[float, float, float, float]]:
    """The part of the picture shown in each frame, in exact (fractional) pixels: no rounding, no shake."""
    boxes = []
    for i in range(frames):
        p = _ease(i / max(1, frames - 1))
        z, cx, cy = 1.0, bw / 2, bh / 2
        if move == "zoom_in":
            z = 1 + 0.16 * p
        elif move == "zoom_out":
            z = 1.16 - 0.16 * p
        elif move == "dolly_in":
            z, cy = 1 + 0.2 * p, bh / 2 - bh * 0.03 * p
        elif move in ("pan_left", "pan_right", "pan_up", "pan_down"):
            z = 1.14
            vw, vh = bw / z, bh / z
            if move == "pan_left":
                cx = bw - vw / 2 - (bw - vw) * p
            elif move == "pan_right":
                cx = vw / 2 + (bw - vw) * p
            elif move == "pan_up":
                cy = bh - vh / 2 - (bh - vh) * p
            else:
                cy = vh / 2 + (bh - vh) * p
        vw, vh = bw / z, bh / z
        x0 = min(max(cx - vw / 2, 0.0), bw - vw)
        y0 = min(max(cy - vh / 2, 0.0), bh - vh)
        boxes.append((x0, y0, x0 + vw, y0 + vh))
    return boxes


def kenburns_frames(path: Path, move: str, w: int, h: int, frames: int):
    """Frames of a smooth camera move over a still, drawn with sub-pixel accuracy (the ffmpeg zoompan filter
    rounds to whole pixels, which is what made slow moves shake)."""
    from PIL import Image
    img = Image.open(path).convert("RGB")
    # crop to the video's shape; keep the picture's own detail (scaling happens per frame)
    target = w / h
    if img.width / img.height > target:
        nw = round(img.height * target)
        img = img.crop(((img.width - nw) // 2, 0, (img.width - nw) // 2 + nw, img.height))
    else:
        nh = round(img.width / target)
        img = img.crop((0, (img.height - nh) // 2, img.width, (img.height - nh) // 2 + nh))
    try:
        import cv2
        import numpy as np
    except ImportError:  # no OpenCV: same smooth motion, just slower
        if img.width < w * 1.2:
            img = img.resize((round(w * 1.2), round(h * 1.2)), Image.LANCZOS)
        for box in kenburns_boxes(move, img.width, img.height, frames):
            yield img.transform((w, h), Image.EXTENT, box, resample=Image.BICUBIC)
        return
    src = np.asarray(img)
    bw, bh = img.width, img.height
    for x0, y0, x1, y1 in kenburns_boxes(move, bw, bh, frames):
        sx, sy = w / (x1 - x0), h / (y1 - y0)
        m = np.array([[sx, 0, -x0 * sx], [0, sy, -y0 * sy]], dtype=np.float64)   # exact, fractional pixels
        out = cv2.warpAffine(src, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
        yield out   # numpy frame; .tobytes() works the same as for a picture


def _cover(w: int, h: int) -> str:
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"


def escape_filter_path(path: Path) -> str:
    text = str(Path(path).resolve()).replace("\\", "/")
    return text.replace(":", "\\:").replace("'", "\\'")


def _smooth(fps: int) -> str:
    """Blend in-between frames so 16 fps AI clips play smoothly at the video's frame rate (no stutter from
    repeated frames)."""
    return f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"


def _render_segment(tl: Timeline, seg: Segment, out: Path, enc: dict) -> None:
    frames = max(1, round(seg.seconds * tl.fps))
    w, h, fps = tl.width, tl.height, tl.fps
    args = [media.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error"]
    piped = None
    if seg.kind == "clip":
        from ..config import settings
        clip_len = max(0.1, media.duration(seg.path) - seg.inpoint)
        # play clips at (nearly) their own speed: a little slow-motion is fine, looping is not
        stretch = min(max(seg.seconds / clip_len, 1.0), 1.35)
        if seg.inpoint:
            args += ["-ss", f"{seg.inpoint:.3f}"]
        args += ["-i", str(seg.path)]
        src_fps = media.fps(seg.path)
        smooth = settings()["video"].get("smooth_clips", True) and (stretch > 1.01 or 0 < src_fps < fps - 0.5)
        chain = (f"[0:v]setpts={stretch:.4f}*PTS," + (_smooth(fps) + "," if smooth else "") +
                 f"fps={fps},{_cover(w, h)},"
                 # if the clip is still shorter than its slot, hold the last frame rather than repeat the clip
                 f"tpad=stop_mode=clone:stop_duration={seg.seconds:.3f},{TO_YUV}")
    elif seg.camera == "static" or frames <= 1:
        args += ["-loop", "1", "-framerate", str(fps), "-t", f"{seg.seconds:.3f}", "-i", str(seg.path)]
        chain = f"[0:v]{_cover(w, h)},{TO_YUV}"
    else:
        args += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-"]
        chain = f"[0:v]{TO_YUV}"
        piped = kenburns_frames(seg.path, seg.camera, w, h, frames)
    if seg.overlay:
        args += ["-i", str(seg.overlay)]
        chain += f"[base];[1:v]scale={w}:{h}[ov];[base][ov]overlay=0:0:format=auto,{TO_YUV}"
    args += ["-filter_complex", chain + "[v]", "-map", "[v]", "-frames:v", str(frames),
             "-c:v", enc["name"], *enc["final"], "-pix_fmt", "yuv420p", *COLOR_TAGS, "-r", str(fps), "-an", str(out)]
    if piped is None:
        run(args, label=f"rendering {seg.label or seg.path.name}", timeout=1800)
        return
    import subprocess
    proc = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0)
    try:
        for frame in piped:
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode("utf-8", "replace")
    if proc.wait() != 0:
        raise StageError(f"Rendering {seg.label or seg.path.name} failed: {err[-400:]}")


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
                         f"volume={tl.speech_db:.2f}dB,apad,atrim=0:{total}[narr]")
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

        if a:
            # overall level: either normalize to the target loudness (raised or lowered by master_db),
            # or just apply master_db
            if tl.loudness_lufs is not None:
                target = max(-30.0, min(-6.0, tl.loudness_lufs + tl.master_db))
                steps.append(f"[{a}]loudnorm=I={target:.1f}:TP=-1.5:LRA=11,aresample=48000,"
                             f"atrim=0:{total}[master]")
            else:
                steps.append(f"[{a}]volume={tl.master_db:.2f}dB,alimiter=limit=0.95[master]")
            a = "master"
        if steps:
            args += ["-filter_complex", ";".join(steps)]
        args += ["-map", "0:v" if v == "0:v" else f"[{v}]"]
        if a:
            args += ["-map", f"[{a}]", "-c:a", "aac", "-b:a", "384k", "-ar", "48000", "-ac", "2"]
        args += ["-t", total, "-c:v", enc["name"], *enc["final"], "-pix_fmt", "yuv420p", *COLOR_TAGS,
                 "-r", str(tl.fps), "-fps_mode", "cfr", "-movflags", "+faststart", str(out)]
        run(args, label="joining the video", timeout=7200)
    finally:
        if keep_temp:
            if on_progress:
                on_progress(f"Working files kept in {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    return {"output": str(out), "seconds": media.duration(out), "encoder": enc["name"],
            "has_audio": media.has_audio(out)}
