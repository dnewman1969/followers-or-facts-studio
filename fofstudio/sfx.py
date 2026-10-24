"""Little sound effects made from scratch (so they're ours, free, and the same every time):
a whoosh when Owlbert flies, a pop when his cap comes off, a sparkle for the prop, a soft musical
sting for a reveal, a stamp thud for the verdict, and a flutter of wings.

Each is a short 48 kHz stereo WAV kept in <data>/sfx/.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from .config import Paths

RATE = 48000


def _env(n: int, attack: float, release: float) -> np.ndarray:
    t = np.arange(n) / RATE
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    r = np.exp(-np.maximum(0, t - attack) / max(release, 1e-4))
    return a * r


def _noise(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n)


def _lowpass(x: np.ndarray, cutoff: np.ndarray | float) -> np.ndarray:
    """One-pole low-pass whose cutoff (Hz) may change over time."""
    c = np.broadcast_to(np.asarray(cutoff, dtype=float), x.shape)
    a = 1 - np.exp(-2 * np.pi * c / RATE)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += a[i] * (x[i] - acc)
        y[i] = acc
    return y


def whoosh(seconds: float = 0.9, seed: int = 1) -> np.ndarray:
    n = int(seconds * RATE)
    t = np.linspace(0, 1, n)
    sweep = 300 + 3200 * np.sin(np.pi * t) ** 2
    x = _lowpass(_noise(n, seed), sweep) * np.sin(np.pi * t) ** 1.5
    return x / (np.abs(x).max() + 1e-9) * 0.5


def flutter(seconds: float = 0.8, rate_hz: float = 9.0, seed: int = 2) -> np.ndarray:
    n = int(seconds * RATE)
    t = np.arange(n) / RATE
    beats = (0.5 + 0.5 * np.sin(2 * np.pi * rate_hz * t)) ** 4
    x = _lowpass(_noise(n, seed), 900.0) * beats * np.sin(np.pi * t / seconds)
    return x / (np.abs(x).max() + 1e-9) * 0.35


def pop() -> np.ndarray:
    n = int(0.18 * RATE)
    t = np.arange(n) / RATE
    f = 900 * np.exp(-t * 30) + 180
    x = np.sin(2 * np.pi * np.cumsum(f) / RATE) * _env(n, 0.002, 0.04)
    return x * 0.6


def sparkle(seed: int = 3) -> np.ndarray:
    n = int(1.2 * RATE)
    out = np.zeros(n)
    rnd = np.random.default_rng(seed)
    for k in range(9):
        start = int(rnd.uniform(0, 0.6) * RATE)
        f = rnd.choice([1568, 1760, 2093, 2349, 2637, 3136])
        m = n - start
        t = np.arange(m) / RATE
        out[start:] += np.sin(2 * np.pi * f * t) * _env(m, 0.003, 0.18) * 0.12
    return out


def sting(minor: bool = False) -> np.ndarray:
    """A soft, bell-like chord hit with a short swell before it (for a reveal)."""
    n = int(2.4 * RATE)
    t = np.arange(n) / RATE
    root = 146.83   # D3
    chord = [1, 1.189, 1.498, 2] if minor else [1, 1.26, 1.498, 2]
    hit = np.zeros(n)
    for k, r in enumerate(chord):
        for h, amp in ((1, 1.0), (2, 0.35), (3, 0.12)):
            hit += amp * np.sin(2 * np.pi * root * r * h * t + k) * np.exp(-t * (1.6 + h))
    hit *= _env(n, 0.006, 3.0)
    swell = _lowpass(_noise(n, 4), 2500.0) * np.clip(1 - t / 0.25, 0, 1) * np.clip(t / 0.2, 0, 1) * 0.15
    x = hit / (np.abs(hit).max() + 1e-9) * 0.6 + swell
    return x


def thud() -> np.ndarray:
    n = int(0.5 * RATE)
    t = np.arange(n) / RATE
    body = np.sin(2 * np.pi * (70 + 60 * np.exp(-t * 25)) * t) * np.exp(-t * 9)
    click = _lowpass(_noise(n, 5), 3000.0) * np.exp(-t * 60) * 0.4
    return (body * 0.8 + click) * 0.7


SOUNDS = {"whoosh": whoosh, "flutter": flutter, "pop": pop, "sparkle": sparkle, "sting": sting,
          "sting_minor": lambda: sting(True), "thud": thud}

# which sounds go with which of Owlbert's moves: (sound, seconds into the move)
MOVE_SOUNDS = {
    "fly_in": [("whoosh", 0.0), ("flutter", 1.3)],
    "fly_out": [("flutter", 0.2), ("whoosh", 0.5)],
    "swoop": [("whoosh", 0.2), ("whoosh", 1.0)],
    "hat_trick": [("pop", 0.3), ("sparkle", 1.05)],
    "stamp": [("thud", 0.33)],
    "surprised": [("pop", 0.1)],
    "flourish": [("flutter", 0.15)],
}


def path(name: str) -> Path:
    """The WAV for a sound, made the first time it's needed."""
    folder = Paths().root / "sfx"
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{name}.wav"
    if not p.exists():
        mono = SOUNDS[name]()
        stereo = np.stack([mono, mono], axis=1)
        data = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
        with wave.open(str(p), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(data.tobytes())
    return p
