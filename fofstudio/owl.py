"""Professor Owlbert as a cut-out puppet: he talks, blinks and appears in every video.

The art comes from brand/owlbert-profile.png. The program cuts the beak in two and
drops the lower jaw by different amounts to make the mouth shapes, draws eyelids
for blinks, and times them to his narration:
  * with Rhubarb Lip Sync (MIT, free Windows download) if it's installed, from the
    sounds he's making;
  * otherwise from how loud each moment of the narration is.
The result is a transparent "presenter" video laid over the corner of the picture,
plus intro and outro bumpers. No AI lip-sync model is needed, so it's fast, runs on
any PC, and the owl always looks exactly like himself.
"""

from __future__ import annotations

import json
import random
import subprocess
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import cards, media
from .config import REPO, Paths, settings
from .util import StageError, run

ART = REPO / "brand" / "owlbert-profile.png"

# Positions in the 1024x1024 profile picture (measured from the art).
BEAK_BOX = (458, 466, 566, 592)     # left, top, right, bottom around the beak
JAW_SPLIT = 538                       # y where the upper beak ends and the lower jaw starts
EYES = [(392, 466), (628, 466)]       # centres of the eye whites
EYE_R = 101                           # radius of the eye whites inside the glasses
FEATHER = (36, 54, 98, 255)
MOUTH = (70, 22, 26, 255)

RIM = (236, 226, 200)  # a soft cream outline around him

# Rhubarb mouth shapes -> how far the jaw drops (pixels at 1024 px) and how wide
SHAPES = {"X": 0, "A": 0, "B": 7, "C": 15, "D": 24, "E": 13, "F": 10, "G": 6, "H": 9}


# The studio background in the art is a flat near-black navy (it varies by at most ~5 levels).
# His black cap is only ~20 levels away from it, so the cut must be tight or the cap vanishes.
BG_TOLERANCE = 11


@lru_cache(maxsize=1)
def base() -> Image.Image:
    """The owl with the studio background removed (full 1024 canvas, positions unchanged).
    A flood fill from the edges takes only pixels within BG_TOLERANCE of the background colour,
    then the edge is smoothed and a thin light rim is added so the black cap and dark-blue wings
    still read against dark scenes."""
    if not ART.exists():
        raise StageError(f"Owlbert's picture is missing: {ART}")
    img = Image.open(ART).convert("RGBA")
    px = img.load()
    w, h = img.size
    bg = px[2, 2]
    from collections import deque
    seen = bytearray(w * h)
    mask = Image.new("L", (w, h), 255)
    mpx = mask.load()
    q = deque([(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)] +
              [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)])
    while q:
        x, y = q.popleft()
        if not (0 <= x < w and 0 <= y < h) or seen[y * w + x]:
            continue
        seen[y * w + x] = 1
        r, g, b, a = px[x, y]
        if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) > BG_TOLERANCE:
            continue
        mpx[x, y] = 0
        q.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))  # clean, soft edge
    # a thin cream rim just outside the outline
    rim_alpha = mask.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(1.5))
    rim = Image.new("RGBA", (w, h), RIM + (0,))
    rim.putalpha(rim_alpha.point(lambda v: int(v * 0.85)))
    img.putalpha(mask)
    rim.alpha_composite(img)
    return rim


def mouth_frame(shape: str, blink: float = 0.0) -> Image.Image:
    """One puppet frame: a mouth shape (Rhubarb letter) and how closed the eyes are (0..1)."""
    return _frame(SHAPES.get(shape, 0), round(blink * 4) / 4).copy()


# The lower half of the beak, as a triangle (left of split, right of split, tip).
JAW_TRI = [(468, JAW_SPLIT), (558, JAW_SPLIT), (512, 590)]
LID = (52, 74, 128, 255)


def _tri_mask(size, pts, grow: int = 3) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).polygon(pts, fill=255)
    return m.filter(ImageFilter.MaxFilter(grow * 2 + 1)) if grow else m


@lru_cache(maxsize=1)
def _rims() -> Image.Image:
    """Mask of the black glasses frames around the eyes."""
    arr = np.asarray(base().convert("RGB")).astype(int)
    lum = arr.mean(axis=2)
    yy, xx = np.mgrid[0:arr.shape[0], 0:arr.shape[1]]
    ring = np.zeros(lum.shape, bool)
    for cx, cy in EYES:
        dist = np.hypot(xx - cx, yy - cy)
        ring |= (dist > EYE_R - 14) & (dist < EYE_R + 22)
    return Image.fromarray(((ring & (lum < 70)) * 255).astype("uint8"), "L")


@lru_cache(maxsize=64)
def _frame(drop: int, blink: float) -> Image.Image:
    img = base().copy()
    if drop:
        mask = _tri_mask(img.size, JAW_TRI, 3)
        jaw = Image.new("RGBA", img.size, (0, 0, 0, 0))
        jaw.paste(img, (0, 0), mask)
        # fill where the jaw was with the face colour, sampled beside the beak, row by row
        d = ImageDraw.Draw(img)
        l, r = JAW_TRI[0][0] - 6, JAW_TRI[1][0] + 6
        mpx = mask.load()
        for y in range(JAW_SPLIT, JAW_TRI[2][1] + 5):
            left, right = img.getpixel((l - 6, y)), img.getpixel((r + 6, y))
            col = tuple((a + b) // 2 for a, b in zip(left, right))
            xs = [x for x in range(l, r) if mpx[x, y]]
            if xs:
                d.line([(min(xs), y), (max(xs), y)], fill=col)
        # the open mouth: a dark wedge under the upper beak
        (x1, y1), (x2, _), (tx, ty) = JAW_TRI
        inset = 10
        d.polygon([(x1 + inset, y1 - 3), (x2 - inset, y1 - 3), (x2 - inset - drop // 2, y1 + drop + 4),
                   (x1 + inset + drop // 2, y1 + drop + 4)], fill=MOUTH)
        img.alpha_composite(jaw, (0, drop))
    if blink > 0:
        lids = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(lids)
        for cx, cy in EYES:
            box = (cx - EYE_R, cy - EYE_R, cx + EYE_R, cy + EYE_R)
            if blink >= 0.99:   # closed: a feathered lid with a happy curved lash line
                d.ellipse(box, fill=LID)
                d.arc((cx - EYE_R * 0.7, cy - 40, cx + EYE_R * 0.7, cy + 30), 20, 160,
                      fill=(15, 15, 25, 255), width=9)
            else:
                lid_y = cy - EYE_R + int(2 * EYE_R * blink)
                d.rectangle((cx - EYE_R, cy - EYE_R, cx + EYE_R, lid_y), fill=LID)
                d.arc((cx - EYE_R, lid_y - 22, cx + EYE_R, lid_y + 22), 0, 180,
                      fill=(15, 15, 25, 255), width=7)
        eyes = Image.new("L", img.size, 0)
        md = ImageDraw.Draw(eyes)
        for cx, cy in EYES:
            md.ellipse((cx - EYE_R, cy - EYE_R, cx + EYE_R, cy + EYE_R), fill=255)
        alpha = Image.composite(lids.split()[3], Image.new("L", img.size, 0), eyes)
        img.paste(lids, (0, 0), alpha)
        img.paste(base(), (0, 0), _rims())  # put the glasses frames back on top of the lids
    return img


# ---------------------------------------------------------------- timing
def rhubarb_cues(wav: Path, text: str | None = None) -> list[tuple[float, str]] | None:
    exe = settings().get("owl", {}).get("rhubarb", "") or "rhubarb"
    try:
        args = [exe, "-f", "json", "--machineReadable", "-r", "phonetic", str(wav)]
        if text:
            dialog = Path(wav).with_suffix(".txt")
            dialog.write_text(text, encoding="utf-8")
            args[1:1] = ["-d", str(dialog)]
        out = run(args, label="Rhubarb lip sync", timeout=600)
        data = json.loads(out.stdout)
        return [(float(c["start"]), c["value"]) for c in data["mouthCues"]]
    except (StageError, ValueError, KeyError):
        return None


def loudness_cues(wav: Path, fps: int = 30) -> list[tuple[float, str]]:
    """Fallback: open the beak by how loud each frame is."""
    with wave.open(str(wav), "rb") as w:
        rate, n, ch, width = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    data = np.frombuffer(raw, dtype={1: np.int8, 2: np.int16, 4: np.int32}[width]).astype(np.float32)
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    hop = max(1, rate // fps)
    frames = len(data) // hop
    if frames == 0:
        return [(0.0, "X")]
    rms = np.sqrt((data[:frames * hop].reshape(frames, hop) ** 2).mean(axis=1))
    peak = np.percentile(rms, 95) or 1.0
    level = np.clip(rms / peak, 0, 1)
    cues: list[tuple[float, str]] = []
    last = None
    for i, v in enumerate(level):
        shape = "X" if v < 0.12 else "B" if v < 0.35 else "C" if v < 0.65 else "D"
        if shape != last:
            cues.append((i / fps, shape))
            last = shape
    return cues


_CUES: dict[tuple, tuple[list[tuple[float, str]], str]] = {}


def cues_for(wav: Path, text: str | None = None) -> tuple[list[tuple[float, str]], str]:
    """Mouth shapes for one line (remembered, since the corner, on-set and move tracks all need them)."""
    try:
        key = (str(wav), Path(wav).stat().st_mtime, text)
    except OSError:
        key = None
    if key in _CUES:
        return _CUES[key]
    cues = rhubarb_cues(wav, text)
    out = (cues, "rhubarb") if cues else (loudness_cues(wav), "loudness")
    if key:
        _CUES[key] = out
    return out


# ---------------------------------------------------------------- presenter video
def speech_timeline(speech: list[tuple[float, Path, str]], progress=lambda t, p=None: None
                    ) -> tuple[list[tuple[float, str]], set[str]]:
    """Every mouth shape change over the whole video: [(time, Rhubarb letter)], and how it was timed."""
    timeline: list[tuple[float, str]] = [(0.0, "X")]
    methods: set[str] = set()
    for k, (start, wav, text) in enumerate(speech):
        progress(f"Timing Owlbert's beak to line {k + 1}/{len(speech)}", 100 * k / max(1, len(speech)))
        cues, method = cues_for(wav, text)
        methods.add(method)
        length = media.duration(wav)
        timeline += [(start + t, s) for t, s in cues if t < length]
        timeline.append((start + length, "X"))
    timeline.sort()
    return timeline, methods


def blink_times(total: float, seed: int = 7) -> list[float]:
    rnd = random.Random(seed)
    blinks: list[float] = []
    t = rnd.uniform(1.5, 3.5)
    while t < total:
        blinks.append(t)
        t += rnd.uniform(2.5, 5.5)
    return blinks


def blink_at(blinks: list[float], t: float) -> float:
    return next((min(1.0, 1 - abs(t - bt) / 0.09) for bt in blinks if abs(t - bt) < 0.09), 0.0)


def shape_at(timeline: list[tuple[float, str]], t: float) -> str:
    import bisect
    i = bisect.bisect_right([x[0] for x in timeline], t) - 1
    return timeline[max(0, i)][1]


def home_box(width: int, height: int) -> tuple[int, int, int, int]:
    """Where the corner presenter sits on screen: left, top, width, height (the render uses the same numbers)."""
    o = settings()["owl"]
    ph = int(height * float(o["presenter_height"]))
    bx0, by0, bx1, by1 = base().getbbox()
    pw = int((bx1 - bx0) * ph / (by1 - by0))
    mx, my = int(width * 0.025), int(height * 0.04)
    corner = o["presenter_corner"]
    x = width - pw - mx if "right" in corner else mx
    y = height - ph - my if "bottom" in corner else my
    return x, y, pw, ph


def presenter_track(speech: list[tuple[float, Path, str]], total: float, out: Path,
                    height: int = 360, fps: int = 30, progress=lambda t, p=None: None) -> Path:
    """Owlbert talking for the whole video, as an ffmpeg "concat" list of transparent PNG
    drawings with how long each one shows. The render lays it straight over the picture,
    so no big intermediate video file is made. Returns the list file (out with .txt).

    speech: (start time on the timeline, narration WAV, its text) for every line he says.
    """
    timeline, methods = speech_timeline(speech, progress)
    blinks = blink_times(total)
    frames_dir = out.parent / (out.stem + "-frames")
    frames_dir.mkdir(parents=True, exist_ok=True)
    cache: dict[tuple[str, float], Path] = {}

    def frame_file(shape: str, blink: float) -> Path:
        key = (shape, blink)
        if key not in cache:
            img = mouth_frame(shape, blink)
            bbox = base().getbbox()
            img = img.crop(bbox)
            w = int(img.width * height / img.height)
            img = img.resize((w, height), Image.LANCZOS)
            p = frames_dir / f"{shape}-{int(blink * 100)}-{height}.png"
            img.save(p)
            cache[key] = p
        return cache[key]

    # concat list: one line per change of picture
    lines = []
    n_frames = int(total * fps)
    idx, current, start_frame = 0, None, 0
    for f in range(n_frames + 1):
        t = f / fps
        while idx + 1 < len(timeline) and timeline[idx + 1][0] <= t:
            idx += 1
        shape = timeline[idx][1] if f < n_frames else "X"
        b = blink_at(blinks, t)
        key = (shape, round(b * 4) / 4)
        if key != current or f == n_frames:
            if current is not None:
                lines.append(f"file '{frame_file(*current).as_posix()}'\nduration {(f - start_frame) / fps:.4f}")
            current, start_frame = key, f
    lines.append(f"file '{frame_file('X', 0.0).as_posix()}'")
    concat = out.with_suffix(".txt")
    concat.write_text("ffconcat version 1.0\n" + "\n".join(lines) + "\n", encoding="utf-8")
    if "loudness" in methods:
        progress("Owlbert's beak is timed by how loud he is. Install Rhubarb Lip Sync (free) for exact "
                 "mouth shapes - see docs/OWLBERT.md", 100)
    else:
        progress("Owlbert's presenter track is ready (Rhubarb lip sync)", 100)
    return concat


# ---------------------------------------------------------------- bumpers
def _bumper_frames(kind: str, title: str, w: int, h: int, fps: int, seconds: float):
    owl = cards.owl()
    size = h // 9
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    while size > 12 and probe.textlength("the facts.", font=cards.font("serif_bold", size)) > w * 0.48:
        size -= 2
    big = cards.font("serif_bold", size)
    small = cards.font("sans_bold", h // 24)
    n = int(seconds * fps)
    bg = cards.owl_backdrop(w, h, 0.25, 0.55)
    for i in range(n):
        t = i / fps
        img = bg.copy()
        d = ImageDraw.Draw(img)
        ease = min(1.0, t / 0.8) ** 0.5
        if owl:
            oh = int(h * 0.62)
            o = owl.resize((int(owl.width * oh / owl.height), oh), Image.LANCZOS)
            bob = int(6 * np.sin(t * 2.2))
            x = int(-o.width + (w * 0.08 + o.width) * ease) if kind == "intro" else int(w * 0.08)
            img.paste(o, (x, int(h * 0.2) + bob), o)
            # name plate: Owlbert is the mascot of Critical Thinking
            plate = cards.font("sans_bold", max(12, h // 40))
            label = "PROF. OWLBERT  ·  CRITICAL THINKING"
            tw = d.textlength(label, font=plate)
            px0 = x + o.width // 2 - int(tw) // 2 - 18
            py0 = int(h * 0.2) + oh + 4
            d.rounded_rectangle((px0, py0, px0 + int(tw) + 36, py0 + plate.size + 18), radius=8,
                                fill=(24, 30, 48), outline=(212, 160, 23), width=2)
            d.text((px0 + 18, py0 + 8), label, font=plate, fill=(212, 160, 23))
        alpha = int(255 * min(1.0, max(0.0, (t - 0.5) / 0.7)))
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        lines = (["Followers", "or Facts"] if kind == "intro" else ["Follow", "the facts."])
        y = int(h * 0.3)
        for ln in lines:
            ld.text((int(w * 0.46), y), ln, font=big, fill=(255, 255, 255, alpha))
            y += int(big.size * 1.15)
        ld.rectangle((int(w * 0.46), y + 10, int(w * 0.46) + 220, y + 18), fill=(212, 160, 23, alpha))
        sub = title if kind == "intro" else "Every source is in the description. Corrections are pinned."
        for k, part in enumerate(cards._wrap(ld, sub, small, int(w * 0.48))[:3]):
            ld.text((int(w * 0.46), y + 40 + k * int(small.size * 1.4)), part, font=small,
                    fill=(250, 240, 220, alpha))
        img = Image.alpha_composite(img.convert("RGBA"), layer)
        fade = min(1.0, t / 0.4, (seconds - t) / 0.5)
        if fade < 1:
            img = Image.blend(Image.new("RGBA", (w, h), (0, 0, 0, 255)), img, max(0.0, fade))
        yield img.convert("RGB")


def bumper(kind: str, title: str, out: Path, width: int = 1920, height: int = 1080, fps: int = 30,
           seconds: float | None = None) -> Path:
    """Intro or outro bumper as an MP4 with a quiet bed of silence (music is added in the mix)."""
    seconds = seconds or (6.0 if kind == "intro" else 8.0)
    out.parent.mkdir(parents=True, exist_ok=True)
    enc = media.encoder("libx264")
    cmd = [media.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{width}x{height}", "-r", str(fps), "-i", "-", "-f", "lavfi", "-i",
           "anullsrc=r=48000:cl=stereo", "-t", f"{seconds:.3f}", "-c:v", enc["name"], *enc["final"],
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0)
    try:
        for frame in _bumper_frames(kind, title, width, height, fps, seconds):
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode("utf-8", "replace")
    if proc.wait() != 0:
        raise StageError(f"Making the {kind} bumper failed: {err[-400:]}")
    return out


# ---------------------------------------------------------------- Rhubarb download (Windows)
RHUBARB_FALLBACK = ("https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v1.14.0/"
                    "Rhubarb-Lip-Sync-1.14.0-Windows.zip")


def download_rhubarb(progress=print) -> Path | None:
    """Fetch Rhubarb Lip Sync (MIT licence) into the data folder and point Settings at it."""
    import io
    import zipfile

    import requests

    from .config import save_settings
    folder = Paths().ensure().models / "rhubarb"
    existing = next(folder.rglob("rhubarb.exe"), None) if folder.exists() else None
    if existing:
        url = None
    else:
        url = RHUBARB_FALLBACK
        try:
            rel = requests.get("https://api.github.com/repos/DanielSWolf/rhubarb-lip-sync/releases/latest",
                               timeout=20).json()
            url = next((a["browser_download_url"] for a in rel.get("assets", [])
                        if "windows" in a["name"].lower() and a["name"].endswith(".zip")), url)
        except Exception:  # noqa: BLE001 - use the known release
            pass
        progress(f"Downloading Rhubarb Lip Sync from {url}")
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        zipfile.ZipFile(io.BytesIO(r.content)).extractall(folder)
        existing = next(folder.rglob("rhubarb.exe"), None)
    if existing:
        s = settings()
        s["owl"]["rhubarb"] = str(existing)
        save_settings(s)
    return existing
