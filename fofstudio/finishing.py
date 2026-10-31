"""Finishing an animated clip (Dave's brief, 2026-10-31: frame interpolation -> temporal consistency -> upscale ->
colour grading -> final clip; the research refined the order: match colours to the still on the original frames,
then interpolate, deflicker only when flicker was found, and upscale last):

  * frame interpolation: Wan makes 16 frames a second; motion-compensated in-between frames bring it to the
    video's frame rate so it doesn't stutter (ffmpeg minterpolate; RIFE in ComfyUI is the upgrade);
  * temporal consistency: deflicker evens out brightness pumping from frame to frame, and every frame's colours
    are pulled toward the storyboard picture the clip started from, so it can't drift in colour;
  * upscale: to the video's size with a sharp Lanczos filter (SeedVR2 in ComfyUI is the upgrade);
  * colour grading: the clip's colours matched to its own storyboard still (Reinhard colour transfer in Lab),
    so a shot looks the same moving as it did on the Storyboard page, and shots in a scene match.

And before any of that, check_clip() looks for a broken clip: sudden jumps between frames (morphing, popping),
black frames, or a clip that hardly moves at all. A broken clip is made again once with a new seed and a simpler,
camera-only motion; if that breaks too, the shot moves in 2.5D instead (video.py).
All local and free: ffmpeg (LGPL/GPL build you already have), OpenCV (Apache-2.0), NumPy (BSD).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from . import media
from .util import run


def _frames(path: Path, size: tuple[int, int] | None = None):
    """Yield RGB frames (uint8) from a video with ffmpeg."""
    w, h = size or media.size(path)
    cmd = [media.ffmpeg(), "-v", "error", "-i", str(path)]
    if size:
        cmd += ["-vf", f"scale={w}:{h}"]
    cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            creationflags=0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0)
    try:
        n = w * h * 3
        while True:
            buf = proc.stdout.read(n)
            if len(buf) < n:
                break
            yield np.frombuffer(buf, np.uint8).reshape(h, w, 3)
    finally:
        proc.stdout.close()
        proc.wait()


def check_clip(path: Path) -> dict[str, Any]:
    """Is this animated clip broken? Frame-to-frame change on small grey frames: a jump far above the clip's
    usual change means morphing or popping; many black frames mean a failed render. Thresholds are starting
    points from the research, to tune on your own clips."""
    diffs, dark, last, lum = [], 0, None, []
    for f in _frames(path, (160, 90)):
        g = f.mean(axis=2)
        dark += g.mean() < 8
        lum.append(float(g.mean()))
        if last is not None:
            diffs.append(float(np.abs(g - last).mean()))
        last = g
    n = len(diffs) + 1
    if n < 3:
        return {"ok": False, "why": "the clip has almost no frames", "frames": n}
    d = np.array(diffs)
    med = float(np.median(d)) + 0.05
    worst = float(d.max())
    jump_at = int(d.argmax()) + 1
    steps = np.abs(np.diff(np.array(lum)))
    flicker = bool(len(steps) > 4 and float(np.median(steps)) > 1.5 and float(np.median(steps)) > 3 * med)
    out = {"frames": n, "median_change": round(med, 2), "biggest_jump": round(worst, 2),
           "dark_frames": int(dark), "break_at": jump_at, "flicker": flicker}
    if dark > 0.1 * n:
        return {**out, "ok": False, "why": f"{dark} black frame(s): the render failed part-way"}
    if worst > 12 and worst > 6 * med:
        return {**out, "ok": False, "why": f"a sudden jump between frames ({worst:.0f} vs a usual {med:.1f}): "
                                           "something morphed or popped"}
    return {**out, "ok": True, "why": "smooth" if med > 0.15 else "very little movement (that's fine)"}


def _lab_stats(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    import cv2
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype(np.float32)
    return lab.reshape(-1, 3).mean(0), lab.reshape(-1, 3).std(0) + 1e-3


def trim(src: Path, dest: Path, frames: int) -> Path:
    """Keep the first `frames` frames (a clip that breaks late is cut just before it breaks)."""
    run([media.ffmpeg(), "-y", "-v", "error", "-i", str(src), "-frames:v", str(max(1, frames)), "-an",
         "-c:v", "libx264", "-crf", "14", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(dest)],
        label=f"trimming {src.name}", timeout=600)
    return dest


def finish_clip(src: Path, still: Path | None, dest: Path, fps: int, width: int, height: int,
                strength: float = 0.6, deflicker: bool = False) -> Path:
    """The finishing order (Dave's brief, refined by the research): colours matched to the storyboard still
    first (temporal consistency, on the few original frames: cheaper and steadier), then interpolation to the
    video's frame rate, then deflicker only when the check found flicker, then the upscale last."""
    import cv2
    src_w, src_h = media.size(src)
    src_fps = media.fps(src) or fps
    target = None
    if still and Path(still).exists():
        img = cv2.cvtColor(cv2.imread(str(still)), cv2.COLOR_BGR2RGB)
        target = _lab_stats(img)
    chain = []
    if 0 < src_fps < fps - 0.5:
        chain.append(f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1")
    if deflicker:
        chain.append("deflicker=mode=pm:size=5")
    chain += [f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos", f"crop={width}:{height}",
              f"fps={fps}"]
    enc = subprocess.Popen([media.ffmpeg(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{src_w}x{src_h}", "-r", f"{src_fps:.4f}", "-i", "-", "-vf", ",".join(chain),
                            "-c:v", "libx264", "-crf", "16", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(dest)],
                           stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           creationflags=0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0)
    try:
        for f in _frames(src):
            if target is not None:
                lab = cv2.cvtColor(f, cv2.COLOR_RGB2LAB).astype(np.float32)
                m, sd = lab.reshape(-1, 3).mean(0), lab.reshape(-1, 3).std(0) + 1e-3
                matched = (lab - m) / sd * target[1] + target[0]
                lab = lab * (1 - strength) + matched * strength
                f = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)
            enc.stdin.write(np.ascontiguousarray(f).tobytes())
    finally:
        enc.stdin.close()
        enc.wait()
    if enc.returncode != 0 or not dest.exists():
        raise RuntimeError(f"finishing {src.name} failed")
    return dest
