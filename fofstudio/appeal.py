"""The colourist's check (Dave, 2026-11-02: "the pics and video are still very bland and not at all visually
pleasing"; research "Animated documentary storytelling craft").

Every painted picture is measured: brightness, contrast and colourfulness (Hasler & Süsstrunk's measure). A
dull one - too dark, too flat or too grey - is lifted gently: its levels are stretched, a dark picture is
brightened, and a grey one gets more colour, unless the style is meant to be black and white. The original is
kept; the numbers before and after go in the picture's record. All local: NumPy and Pillow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

MONO_WORDS = ("black and white", "black-and-white", "monochrome", "greyscale", "grayscale", "kinescope",
              "silhouette", "noir", "sepia", "shadow puppet", "pinscreen", "charcoal", "pencil sketch", "ink wash")
# starting points from the research (to tune on pictures Dave marks as good or dull)
MIN_BRIGHT, MIN_CONTRAST, MIN_COLOUR = 0.36, 0.17, 22.0


def measure(img) -> dict[str, float]:
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    lum = (0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]) / 255.0
    rg = a[..., 0] - a[..., 1]
    yb = 0.5 * (a[..., 0] + a[..., 1]) - a[..., 2]
    colour = float(np.hypot(rg.std(), yb.std()) + 0.3 * np.hypot(rg.mean(), yb.mean()))
    return {"brightness": round(float(lum.mean()), 3), "contrast": round(float(lum.std()), 3),
            "colourfulness": round(colour, 1)}


def is_mono(look: str) -> bool:
    low = (look or "").lower()
    return any(w in low for w in MONO_WORDS)


def dull(m: dict[str, float], mono: bool = False) -> list[str]:
    why = []
    if m["brightness"] < MIN_BRIGHT:
        why.append("too dark")
    if m["contrast"] < MIN_CONTRAST:
        why.append("flat")
    if not mono and m["colourfulness"] < MIN_COLOUR:
        why.append("grey")
    return why


def lift(src: Path, dest: Path, look: str = "") -> dict[str, Any]:
    """Measure the picture; if it's dull, save a lifted copy at `dest` (else nothing is written)."""
    from PIL import Image, ImageEnhance
    img = Image.open(src).convert("RGB")
    before = measure(img)
    mono = is_mono(look)
    why = dull(before, mono)
    if "too dark" not in why and "grey" not in why:    # flat colour on its own is a style, not a fault
        return {"before": before, "lifted": False, "why": why}
    a = np.asarray(img, dtype=np.float32) / 255.0
    lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    lo, hi = np.percentile(lum, 0.5), np.percentile(lum, 99.5)
    new = np.clip((lum - lo) / (hi - lo), 0, 1) if hi - lo > 0.06 else lum.copy()   # stretch the lightness
    if new.mean() < lum.mean() - 0.01:                   # never darker than it was
        new = lum.copy()
    if new.mean() < 0.42:                                # a gentle lift of the mid-tones for a dark picture
        new = np.power(new, np.log(0.45) / np.log(max(0.06, float(new.mean()))))
    a = a * (new / np.maximum(lum, 1e-3))[..., None]     # every pixel keeps its own hue
    out = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8), "RGB")
    if not mono and "grey" in why:
        out = ImageEnhance.Color(out).enhance(1.3)
    out = ImageEnhance.Contrast(out).enhance(1.06)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.save(dest)
    return {"before": before, "after": measure(out), "lifted": True, "why": why}
