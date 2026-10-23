"""Owlbert's moves ("bits"): flying in, flying off, pointing at the evidence, a wing flourish, and the
hat trick, where he takes off his cap, turns it over and pulls out the trick of the day.

Each move has a teaching job and a place in the video (the research behind this is in
docs/OWLBERT.md): he flies in to start the story, points at the evidence while it's on screen,
pulls the named trick out of his hat in the "tell" scene, a light bulb out of it for the
"toolkit" question, gives the verdict a flourish, and flies off before the outro.
The planner keeps them rare: at most one big move a scene, and none of the playful ones
(hat trick, flourish) in videos about deaths, victims or other careful topics.

The moves are drawn with the cut-out rig in rig.py onto transparent full-size frames, and the
render lays them over the picture. Owlbert's beak keeps moving with his narration while he flies.
"""

from __future__ import annotations

import math
import random
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageDraw

from . import cards, owl, rig
from .rig import Pose

KINDS = {
    "fly_in": "Fly in",
    "point": "Point at the evidence",
    "hat_trick": "Hat trick",
    "flourish": "Wing flourish",
    "fly_out": "Fly off",
}
LENGTH = {"fly_in": 2.4, "point": 2.4, "hat_trick": 5.2, "flourish": 1.6, "fly_out": 2.0}
BIG = {"fly_in", "hat_trick", "flourish", "fly_out"}
PLAYFUL = {"hat_trick", "flourish"}
POINT_ROLES = ("record", "claim", "harm", "benefit")


def _ease(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return p * p * (3 - 2 * p)


def _ease_out(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return 1 - (1 - p) ** 3


def _ease_in(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return p * p


def _back(p: float, s: float = 1.7) -> float:
    """Ease out with a little overshoot."""
    p = max(0.0, min(1.0, p)) - 1
    return p * p * ((s + 1) * p + s) + 1


def _ramp(t: float, a: float, b: float) -> float:
    return _ease((t - a) / (b - a)) if b > a else float(t >= b)


def _catmull(pts: list[tuple[float, float]], u: float) -> tuple[float, float]:
    """A smooth path through the points, u from 0 to 1."""
    n = len(pts) - 1
    u = max(0.0, min(1.0, u)) * n
    i = min(int(u), n - 1)
    t = u - i
    p0, p1, p2, p3 = pts[max(0, i - 1)], pts[i], pts[i + 1], pts[min(n, i + 2)]
    return tuple(0.5 * (2 * p1[c] + (-p0[c] + p2[c]) * t + (2 * p0[c] - 5 * p1[c] + 4 * p2[c] - p3[c]) * t * t
                        + (-p0[c] + 3 * p1[c] - 3 * p2[c] + p3[c]) * t ** 3) for c in (0, 1))


# ---------------------------------------------------------------- props
@lru_cache(maxsize=16)
def prop_image(kind: str, text: str = "", height: int = 300) -> Image.Image:
    """The things he pulls out of his hat, drawn at the given height."""
    ss = 2
    h = height * ss
    if kind == "card":
        w = int(h * 1.5)
        img = Image.new("RGBA", (w + 24 * ss, h + 24 * ss), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((14 * ss, 18 * ss, w + 18 * ss, h + 22 * ss), radius=28 * ss, fill=(0, 0, 0, 90))
        d.rounded_rectangle((6 * ss, 6 * ss, w + 6 * ss, h + 6 * ss), radius=28 * ss, fill=(250, 240, 220, 255),
                            outline=(212, 160, 23, 255), width=9 * ss)
        band = int(h * 0.26)
        d.rounded_rectangle((15 * ss, 15 * ss, w - 3 * ss, band), radius=20 * ss, fill=(24, 30, 48, 255))
        small = cards.font("sans_bold", int(band * 0.42))
        label = "THE TRICK"
        d.text(((w + 12 * ss - d.textlength(label, font=small)) / 2, 15 * ss + (band - 15 * ss - small.size) / 2 - 2),
               label, font=small, fill=(212, 160, 23, 255))
        size = int(h * 0.2)
        while size > 10:
            big = cards.font("serif_bold", size)
            lines = cards._wrap(d, text.upper() or "?", big, w - 70 * ss)
            if len(lines) <= 2 and all(d.textlength(x, font=big) <= w - 70 * ss for x in lines):
                break
            size -= 4
        y = band + (h - band - len(lines) * size * 1.15) / 2
        for ln in lines:
            d.text(((w + 12 * ss - d.textlength(ln, font=big)) / 2, y), ln, font=big, fill=(24, 30, 48, 255))
            y += size * 1.15
    elif kind == "bulb":
        w = int(h * 0.75)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        cx, r = w / 2, w * 0.36
        for k in range(10):                                        # rays
            a = math.pi * (0.95 + 1.1 * k / 9)
            d.line((cx + math.cos(a) * r * 1.2, r * 1.3 + math.sin(a) * r * 1.2, cx + math.cos(a) * r * 1.5,
                    r * 1.3 + math.sin(a) * r * 1.5), fill=(255, 214, 90, 255), width=7 * ss)
        d.ellipse((cx - r - 6 * ss, r * 0.3 - 6 * ss, cx + r + 6 * ss, r * 2.3 + 6 * ss), fill=(20, 20, 30, 255))
        d.ellipse((cx - r, r * 0.3, cx + r, r * 2.3), fill=(255, 222, 102, 255))
        d.ellipse((cx - r * 0.55, r * 0.55, cx - r * 0.1, r * 1.0), fill=(255, 248, 210, 255))
        d.polygon([(cx - r * 0.5, r * 2.0), (cx + r * 0.5, r * 2.0), (cx + r * 0.35, h * 0.86),
                   (cx - r * 0.35, h * 0.86)], fill=(255, 222, 102, 255), outline=(20, 20, 30, 255))
        for k in range(3):
            y = h * 0.86 + k * h * 0.04
            d.rounded_rectangle((cx - r * 0.42, y, cx + r * 0.42, y + h * 0.035), radius=4 * ss,
                                fill=(150, 156, 170, 255), outline=(20, 20, 30, 255), width=2 * ss)
    else:   # magnifying glass
        w = h
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        r = h * 0.3
        cx, cy = w * 0.4, h * 0.4
        d.line((cx + r * 0.7, cy + r * 0.7, w * 0.92, h * 0.92), fill=(20, 20, 30, 255), width=int(h * 0.13))
        d.line((cx + r * 0.75, cy + r * 0.75, w * 0.9, h * 0.9), fill=(140, 82, 40, 255), width=int(h * 0.09))
        d.ellipse((cx - r - h * 0.06, cy - r - h * 0.06, cx + r + h * 0.06, cy + r + h * 0.06), fill=(20, 20, 30, 255))
        d.ellipse((cx - r - h * 0.035, cy - r - h * 0.035, cx + r + h * 0.035, cy + r + h * 0.035),
                  fill=(212, 160, 23, 255))
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(200, 230, 245, 200))
        d.arc((cx - r * 0.7, cy - r * 0.7, cx + r * 0.7, cy + r * 0.7), 200, 260, fill=(255, 255, 255, 255),
              width=int(h * 0.03))
    return img.resize((max(1, img.width // ss), max(1, img.height // ss)), Image.LANCZOS)


def _star(d: ImageDraw.ImageDraw, x: float, y: float, r: float, color, alpha: int) -> None:
    pts = []
    for k in range(8):
        a = math.pi * k / 4
        rr = r if k % 2 == 0 else r * 0.32
        pts.append((x + math.cos(a) * rr, y + math.sin(a) * rr))
    d.polygon(pts, fill=color + (alpha,))


class Sparkles:
    """A burst of little gold and white stars."""

    def __init__(self):
        self.bursts: list[tuple[float, float, float, float, int]] = []

    def burst(self, t: float, x: float, y: float, size: float, n: int = 18) -> None:
        self.bursts.append((t, x, y, size, n))

    def draw(self, img: Image.Image, t: float) -> None:
        d = ImageDraw.Draw(img)
        for k, (t0, x, y, size, n) in enumerate(self.bursts):
            age = t - t0
            if not 0 <= age <= 0.9:
                continue
            rnd = random.Random(k * 977 + 13)
            for _ in range(n):
                a = rnd.uniform(0, 2 * math.pi)
                v = rnd.uniform(0.6, 1.0) * size * 2.2
                px = x + math.cos(a) * v * _ease_out(age / 0.9)
                py = y + math.sin(a) * v * _ease_out(age / 0.9) - size * 0.4 * age
                r = size * rnd.uniform(0.08, 0.16) * (1 - age / 0.9) ** 0.5
                col = (255, 236, 150) if rnd.random() < 0.6 else (255, 255, 255)
                _star(d, px, py, r, col, int(255 * (1 - age / 0.9)))


# ---------------------------------------------------------------- the moves
class Move:
    """One move, drawn frame by frame. pose_at() gives the rig pose; extras() draws props on top."""

    def __init__(self, stage: rig.Stage, kind: str, duration: float, prop: dict | None = None, variant: int = 0):
        self.st, self.kind, self.d, self.prop, self.variant = stage, kind, duration, prop or {}, variant
        self.sparkles = Sparkles()
        self.dim = 0.0
        w, h = stage.w, stage.h
        hx, hy = stage.home
        inward = stage.inward
        if kind == "fly_in":
            start_x = w * (0.5 + inward * 0.62)       # from the far side of the screen
            mid1 = (w * (0.5 + inward * 0.25), h * (0.12 if variant % 2 == 0 else 0.42))
            mid2 = (hx + inward * w * 0.18, h * (0.36 if variant % 2 == 0 else 0.16))
            self.path = [(start_x, h * (0.22 if variant % 2 == 0 else 0.05)), mid1, mid2,
                         (hx + inward * w * 0.02, hy - h * 0.12), (hx, hy)]
        elif kind == "fly_out":
            exit_x = w * (0.5 - inward * 0.75)          # off the edge he sits nearest to
            self.path = [(hx, hy), (hx - inward * w * 0.03, hy - h * 0.18), (hx - inward * w * 0.1, h * 0.25),
                         (exit_x, -h * 0.25)]
        if kind == "hat_trick":
            px = hx + inward * (w * 0.32)
            self.spot = (max(w * 0.18, min(w * 0.82, px)), h * 0.40)
            self.prop_h = int(h * 0.30)

    # ------------------------------------------------------------ poses
    def pose_at(self, t: float, base: Pose) -> Pose:
        f = getattr(self, "_" + self.kind)
        return f(t, base)

    def _flap(self, t: float, speed: float = 3.2, amp: float = 34, lift: float = 6) -> float:
        return lift + amp * math.sin(2 * math.pi * speed * t)

    def _fly(self, t: float, base: Pose, u: float) -> Pose:
        x, y = _catmull(self.path, u)
        x2, _ = _catmull(self.path, min(1.0, u + 0.02))
        vx = x2 - x
        bank = max(-16.0, min(16.0, -vx / self.st.w * 900))
        flap = self._flap(t)
        bob = -math.sin(2 * math.pi * 3.2 * t + 0.6) * self.st.h * 0.008
        return replace(base, x=x, y=y + bob, rot=bank, spread=1.0, flap_l=flap, flap_r=flap)

    def _fly_in(self, t: float, base: Pose) -> Pose:
        land = self.d - 0.35
        p_ = max(0.0, min(1.0, t / land))
        u = 1 - (1 - p_) ** 2
        p = self._fly(t, base, u)
        if t >= land - 0.25:                       # flare the wings, then fold them
            k = _ramp(t, land - 0.25, land)
            p.flap_l = p.flap_r = p.flap_l * (1 - k) + 38 * k
            p.rot *= 1 - k
        if t >= land:
            k = (t - land) / 0.35
            p.x, p.y, p.rot = base.x, base.y, 0.0
            p.spread = max(0.0, 1 - k * 3)
            p.squash = 0.07 * math.sin(math.pi * min(1.0, k))
        return p

    def _fly_out(self, t: float, base: Pose) -> Pose:
        crouch = 0.3
        if t < crouch:
            k = t / crouch
            return replace(base, squash=0.08 * _ease(k), spread=_ramp(t, 0.12, crouch), flap_l=20, flap_r=20)
        u = _ease_in((t - crouch) / (self.d - crouch))
        p = self._fly(t, base, u)
        p.squash = -0.05 * (1 - _ramp(t, crouch, crouch + 0.25))
        return p

    def _point(self, t: float, base: Pose) -> Pose:
        up = _ramp(t, 0.15, 0.5) * (1 - _ramp(t, self.d - 0.45, self.d))
        look = _ramp(t, 0.0, 0.2) * (1 - _ramp(t, self.d - 0.3, self.d))
        wiggle = 5 * math.sin(2 * math.pi * 1.6 * t) * up
        angle = (68 if self.variant % 2 == 0 else 52) * up + wiggle
        p = replace(base, gaze=round(2 * look) * self.st.inward, rot=-2.5 * up * self.st.inward)
        if self.st.inward < 0:
            p.wing_l = angle
        else:
            p.wing_r = angle
        return p

    def _flourish(self, t: float, base: Pose) -> Pose:
        open_ = _ramp(t, 0.0, 0.2) * (1 - _ramp(t, self.d - 0.3, self.d - 0.05))
        flap = 18 + 26 * math.sin(2 * math.pi * 2.6 * (t - 0.2)) if t > 0.2 else 18
        hop = math.sin(math.pi * _ramp(t, 0.15, self.d - 0.3)) * self.st.h * 0.025
        return replace(base, y=base.y - hop, spread=open_, flap_l=flap * open_, flap_r=flap * open_)

    def _hat_trick(self, t: float, base: Pose) -> Pose:
        inward = self.st.inward
        d = self.d
        p = replace(base)
        # the wing on the inside waves like a magician, and stays up while he holds the hat
        wave = _ramp(t, 0.0, 0.35) * (1 - _ramp(t, d - 0.9, d - 0.5))
        ang = 80 * wave + 6 * math.sin(2 * math.pi * 1.2 * t) * wave
        if inward < 0:
            p.wing_l = ang
        else:
            p.wing_r = ang
        p.gaze = round(2 * _ramp(t, 0.9, 1.1) * (1 - _ramp(t, d - 1.0, d - 0.8))) * inward
        # the cap pops up, moves beside him and turns over; at the end it comes back
        up = _back(_ramp(t, 0.25, 0.55) if t < 0.55 else 1.0)
        go = _ease(_ramp(t, 0.5, 1.0))
        back = _ramp(t, d - 0.95, d - 0.25)
        hover_dx, hover_dy = inward * 590, 70
        dx = hover_dx * go
        dy = -260 * up * (1 - go) + hover_dy * go
        flip = _ease(_ramp(t, 0.55, 1.0))
        if back > 0:
            flip = 1 - _ease(_ramp(t, d - 0.95, d - 0.6))
            dx = hover_dx * (1 - back)
            dy = hover_dy * (1 - back) - 200 * math.sin(math.pi * back)
        p.cap_dx, p.cap_dy, p.cap_flip = dx, dy, flip
        p.cap_rot = 10 * math.sin(math.pi * _ramp(t, 0.25, 1.0)) * -inward
        settle = _ramp(t, d - 0.25, d)
        p.squash = 0.05 * math.sin(math.pi * settle) if settle > 0 else 0.0
        return p

    # ------------------------------------------------------------ extras on top
    def extras(self, t: float, pose: Pose, img: Image.Image, cap_opening: tuple[float, float] | None) -> None:
        if self.kind != "hat_trick" or cap_opening is None:
            return
        d = self.d
        ox, oy = cap_opening
        emerge, present, gone = 1.1, 1.75, d - 1.2
        if t < emerge - 0.05:
            return
        if not getattr(self, "_burst1", False):
            self.sparkles.burst(emerge - 0.05, ox, oy, self.prop_h * 0.35)
            self.sparkles.burst(gone, self.spot[0], self.spot[1], self.prop_h * 0.6, 26)
            self._burst1 = True
        if t < gone:
            k = _ramp(t, emerge, present)
            scale = 0.25 + 0.75 * _back(min(1.0, (t - emerge) / (present - emerge)))
            x = ox + (self.spot[0] - ox) * _ease(k)
            y = (oy - self.prop_h * 0.15) + (self.spot[1] - (oy - self.prop_h * 0.15)) * _ease(k)
            y += math.sin(2 * math.pi * 0.7 * t) * self.prop_h * 0.03 * k
            pic = prop_image(self.prop.get("kind", "card"), self.prop.get("text", ""), self.prop_h)
            pw, ph = max(1, int(pic.width * scale)), max(1, int(pic.height * scale))
            pic = pic.resize((pw, ph), Image.LANCZOS)
            left, top = int(x - pw / 2), int(y - ph / 2)
            if k < 0.5:                                  # still coming out: hide what's inside the hat
                arr = np.asarray(pic).copy()
                rim_row = int(oy) - top
                if rim_row < ph:
                    arr[max(0, rim_row):, :, 3] = 0
                pic = Image.fromarray(arr, "RGBA")
            _paste(img, pic, left, top)
        self.sparkles.draw(img, t)

    def dim_at(self, t: float) -> float:
        if self.kind != "hat_trick":
            return 0.0
        return 0.35 * _ramp(t, 1.2, 1.7) * (1 - _ramp(t, self.d - 1.3, self.d - 0.9))


def _paste(img: Image.Image, pic: Image.Image, left: int, top: int) -> None:
    """alpha_composite that tolerates a picture hanging off the frame."""
    box = (max(0, left), max(0, top), min(img.width, left + pic.width), min(img.height, top + pic.height))
    if box[2] <= box[0] or box[3] <= box[1]:
        return
    part = pic.crop((box[0] - left, box[1] - top, box[2] - left, box[3] - top))
    img.alpha_composite(part, (box[0], box[1]))


# ---------------------------------------------------------------- drawing a move
class Tassel:
    """The tassel swings behind the cap like a pendulum, so it lags when he moves."""

    def __init__(self, fps: int):
        self.dt = 1.0 / fps
        self.angle, self.speed = 0.0, 0.0
        self.last: tuple[float, float] | None = None

    def step(self, pivot_screen: tuple[float, float], extra_tilt: float) -> float:
        vx = 0.0
        if self.last is not None:
            vx = (pivot_screen[0] - self.last[0]) / self.dt
        self.last = pivot_screen
        target = max(-40.0, min(40.0, vx * 0.03)) - extra_tilt
        acc = -(2 * math.pi * 1.3) ** 2 * (self.angle - target) - 2 * 0.3 * (2 * math.pi * 1.3) * self.speed
        self.speed += acc * self.dt
        self.angle += self.speed * self.dt
        return self.angle


def frames(stage: rig.Stage, kind: str, duration: float, fps: int, mouth: Callable[[float], tuple[str, float]],
           prop: dict | None = None, variant: int = 0):
    """Yield (time, transparent RGBA frame) for one move. mouth(t) gives (shape, blink) at time t of the move."""
    mv = Move(stage, kind, duration, prop, variant)
    tassel = Tassel(fps)
    n = max(1, int(round(duration * fps)))
    for i in range(n):
        t = i / fps
        shape, blink = mouth(t)
        base = replace(stage.rest(), shape=shape, blink=blink)
        pose = mv.pose_at(t, base)
        art = stage.tassel_pivot(pose)
        sx, sy = _apply(stage.to_screen(pose), art)
        pose.tassel = tassel.step((sx, sy), pose.rot + (pose.cap_rot if pose.cap_flip <= 0.5 else 0))
        frame = np.zeros((stage.h, stage.w, 4), np.float32)
        dim = mv.dim_at(t)
        if dim > 0:
            frame[..., 3] = dim
        stage.draw(pose, frame)
        img = rig.to_image(frame)
        opening = None
        if pose.cap_flip > 0.5:
            m, _ = stage.cap_matrix(pose)
            ax, ay = _apply(m, rig.CAP_PIVOT)
            opening = _apply(stage.to_screen(pose), (ax, ay))
        mv.extras(t, pose, img, opening)
        yield t, img


def _apply(m: np.ndarray, pt: tuple[float, float]) -> tuple[float, float]:
    v = m @ np.array([pt[0], pt[1], 1.0])
    return float(v[0]), float(v[1])


# ---------------------------------------------------------------- planning
def plan(scenes: list[dict[str, Any]], creative: dict[str, Any], tricks: list[str], seed: str = "") -> list[dict]:
    """Choose Owlbert's moves for a video.

    scenes: in order, each {"scene_id", "role", "start", "speech_start", "speech_end", "end"} in timeline seconds.
    creative: the episode's creative settings (careful, humor). tricks: technique keys the story teaches.
    """
    from . import techniques
    rnd = random.Random(seed or "owlbert")
    careful = bool(creative.get("careful"))
    playful_ok = not careful
    bits: list[dict[str, Any]] = []
    big_times: list[float] = []

    def ok_big(t: float) -> bool:
        return all(abs(t - b) >= 20 for b in big_times)

    def add(kind: str, start: float, sc: dict, **extra) -> None:
        bits.append({"id": f"{kind}-{len(bits) + 1}", "kind": kind, "start": round(max(0.0, start), 3),
                     "duration": LENGTH[kind], "scene_id": sc["scene_id"], "label": KINDS[kind], **extra})
        if kind in BIG:
            big_times.append(start)

    if not scenes:
        return []
    first = scenes[0]
    add("fly_in", first["start"], first, variant=rnd.randrange(2))
    hats = 0
    points_last = -999.0
    point_variant = 0
    for sc in scenes[1:-1] if len(scenes) > 2 else scenes[1:]:
        role = sc.get("role")
        talk = sc["speech_end"] - sc["speech_start"]
        if role == "tell" and playful_ok and hats < 2 and talk > 6:
            t = sc["speech_start"] + min(2.0, talk * 0.2)
            if ok_big(t):
                tech = techniques.get(tricks[0]) if tricks else None
                add("hat_trick", t, sc, prop={"kind": "card", "text": tech.name if tech else "The Trick"})
                hats += 1
                continue
        if role == "toolkit" and playful_ok and hats < 2 and talk > 6:
            t = sc["speech_start"] + min(1.5, talk * 0.2)
            if ok_big(t):
                add("hat_trick", t, sc, prop={"kind": "bulb", "text": ""})
                hats += 1
                continue
        if role == "verdict" and playful_ok and int(creative.get("humor", 1)) > 0 and talk > 3:
            t = sc["speech_start"] + 0.3
            if ok_big(t):
                add("flourish", t, sc)
                continue
        if role in POINT_ROLES and talk > 8 and sc["speech_start"] - points_last >= 25:
            t = sc["speech_start"] + min(3.0, talk * 0.25)
            add("point", t, sc, variant=point_variant)
            point_variant += 1
            points_last = t
    last = scenes[-1]
    if len(scenes) > 1:
        start = max(last["speech_start"] + 0.5, last["end"] - LENGTH["fly_out"])
        add("fly_out", start, last)
    # never two moves at once
    bits.sort(key=lambda b: b["start"])
    out: list[dict[str, Any]] = []
    for b in bits:
        if out and b["start"] < out[-1]["start"] + out[-1]["duration"] + 0.5:
            continue
        out.append(b)
    return out


def scenes_from_timeline(tl: dict[str, Any], roles: dict[str, str]) -> list[dict[str, Any]]:
    """The scene timings the planner needs, from a production timeline."""
    out = []
    speech = {c["scene_id"]: c for c in tl.get("speech", [])}
    clips: dict[str, list[dict]] = {}
    for c in tl.get("video", []):
        if c.get("kind") == "clip":
            clips.setdefault(c["scene_id"], []).append(c)
    for sid, cs in clips.items():
        start = min(c["start"] for c in cs)
        end = max(c["start"] + c["duration"] for c in cs)
        sp = speech.get(sid)
        out.append({"scene_id": sid, "role": roles.get(sid, ""), "start": start, "end": end,
                    "speech_start": sp["start"] if sp else start,
                    "speech_end": sp["start"] + sp["duration"] if sp else end})
    out.sort(key=lambda s: s["start"])
    return out


def subtract(ranges: list[tuple[float, float]], holes: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Time ranges with the holes cut out (Owlbert in the corner hides while a move plays)."""
    out = []
    for a, b in ranges:
        pieces = [(a, b)]
        for h0, h1 in holes:
            nxt = []
            for x, y in pieces:
                if h1 <= x or h0 >= y:
                    nxt.append((x, y))
                    continue
                if x < h0:
                    nxt.append((x, h0))
                if h1 < y:
                    nxt.append((h1, y))
            pieces = nxt
        out += [(x, y) for x, y in pieces if y - x > 0.02]
    return out


def merge(ranges: list[tuple[float, float]], gap: float = 2.5) -> list[tuple[float, float]]:
    """Join ranges closer than `gap` seconds, so he doesn't blink out of the corner between scenes."""
    out: list[list[float]] = []
    for a, b in sorted(ranges):
        if out and a - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


# ---------------------------------------------------------------- the track the render lays over the picture
def render_track(moves: list[dict[str, Any]], speech: list[tuple[float, Path, str]], total: float, out: Path,
                 width: int, height: int, fps: int, progress=lambda t, p=None: None) -> tuple[Path, list]:
    """Draw every move onto transparent full-size frames and list them for ffmpeg ("concat" file).
    Returns the list file and the time ranges the moves cover."""
    timeline, _ = owl.speech_timeline(speech) if speech else ([(0.0, "X")], set())
    blinks = owl.blink_times(total)
    stage = rig.Stage(width, height)
    frames_dir = out.parent / (out.stem + "-frames")
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("*.png"):
        old.unlink()
    blank = frames_dir / "blank.png"
    Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(blank)
    lines: list[str] = []
    ranges: list[tuple[float, float]] = []
    t_cursor = 0.0
    moves = sorted(moves, key=lambda m: m["start"])
    for k, mv in enumerate(moves):
        start = max(t_cursor, round(mv["start"] * fps) / fps)
        dur = float(mv.get("duration") or LENGTH.get(mv["kind"], 2.0))
        if start >= total or mv["kind"] not in KINDS:
            continue
        dur = min(dur, total - start)
        progress(f"Drawing Owlbert's {KINDS[mv['kind']].lower()} ({k + 1}/{len(moves)})", 100 * k / max(1, len(moves)))
        if start > t_cursor:
            lines.append(f"file '{blank.as_posix()}'\nduration {start - t_cursor:.4f}")

        def mouth(t, s0=start):
            return owl.shape_at(timeline, s0 + t), owl.blink_at(blinks, s0 + t)

        n = 0
        for i, (_, img) in enumerate(frames(stage, mv["kind"], dur, fps, mouth, mv.get("prop"), mv.get("variant", 0))):
            f = frames_dir / f"{k:02d}-{i:04d}.png"
            img.save(f, compress_level=1)
            lines.append(f"file '{f.as_posix()}'\nduration {1 / fps:.6f}")
            n += 1
        ranges.append((start, start + n / fps))
        t_cursor = start + n / fps
    if t_cursor < total:
        lines.append(f"file '{blank.as_posix()}'\nduration {total - t_cursor:.4f}")
    lines.append(f"file '{blank.as_posix()}'")
    concat = out.with_suffix(".txt")
    concat.write_text("ffconcat version 1.0\n" + "\n".join(lines) + "\n", encoding="utf-8")
    progress("Owlbert's moves are drawn", 100)
    return concat, ranges
