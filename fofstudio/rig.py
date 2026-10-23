"""Owlbert as a cut-out puppet with moving parts: wings that lift and flap, a cap that comes off,
a tassel that swings, and eyes that look where he points.

The parts are cut from the same picture as the talking puppet (brand/owlbert-profile.png):
  * cap (board and skull cap) and tassel - cut by colour inside the cap's outline;
  * the two folded wings - cut along the line where each wing meets his body.
The program also draws the few things the picture doesn't contain:
  * the top of his head (hidden under the cap in the picture);
  * spread wings for flying (one drawing; the right wing is the same drawing flipped -
    only the wing, never Owlbert himself, so the tassel always stays on the viewer's right);
  * the inside of the cap, for when he turns it over to pull something out;
  * the props he pulls out: a trick card with the trick's name, a magnifying glass, a light bulb.

Everything is drawn with Pillow and OpenCV, so it is free, fast and always on model.
Positions below are in the 1024 x 1024 picture ("art" coordinates).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import owl

NAVY = (36, 54, 98)
NAVY_DARK = (26, 40, 76)
NAVY_LIGHT = (58, 88, 146)
INK = (12, 16, 30)
GOLD = (212, 160, 23)
CREAM = (250, 240, 220)

# The cap: a generous outline (the cut keeps only the non-blue pixels inside it)
CAP_OUTLINE = [(186, 196), (512, 76), (840, 208), (836, 228), (694, 268), (686, 302), (512, 328),
               (342, 294), (338, 262), (192, 212)]
CAP_PIVOT = (512, 236)                 # where the cap sits on his head
TASSEL_BOX = (745, 165, 875, 505)      # left, top, right, bottom around the cord and tassel
TASSEL_PIVOT = (788, 192)              # where the cord bends over the edge of the board

# The left wing (viewer's left). The right wing is the same shape across the middle (x -> 1024 - x).
WING_OUTER = [(268, 538), (238, 546), (204, 574), (184, 620), (178, 680), (192, 742), (216, 796), (244, 828)]
WING_INNER = [(244, 828), (272, 796), (281, 740), (283, 660), (279, 590), (268, 538)]   # bottom to top
WING_PIVOT = (262, 566)                # the shoulder
SPREAD_PIVOT = (285, 600)              # where a spread wing joins the body

HEAD_TOP = (262, 196, 762, 470)        # the dome drawn under the cap (an ellipse box)


@dataclass
class Part:
    img: np.ndarray            # premultiplied RGBA float32, 0..1
    origin: tuple[float, float]  # art position of the image's top-left pixel
    pivot: tuple[float, float]   # art position it turns around


def _premul(img: Image.Image) -> np.ndarray:
    a = np.asarray(img.convert("RGBA")).astype(np.float32) / 255.0
    a[..., :3] *= a[..., 3:4]
    return a


def _part(img: Image.Image, pivot, pad: int = 2) -> Part:
    box = img.getbbox() or (0, 0, 1, 1)
    box = (max(0, box[0] - pad), max(0, box[1] - pad), min(img.width, box[2] + pad), min(img.height, box[3] + pad))
    return Part(_premul(img.crop(box)), (box[0], box[1]), pivot)


def _mirror_pts(pts):
    return [(1024 - x, y) for x, y in pts]


def _poly_mask(pts, size=(1024, 1024)) -> np.ndarray:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).polygon(pts, fill=255)
    return np.asarray(m) > 0


def _dilate(mask: np.ndarray, r: int) -> np.ndarray:
    img = Image.fromarray(mask.astype("uint8") * 255).filter(ImageFilter.MaxFilter(2 * r + 1))
    return np.asarray(img) > 0


def _edge_x(pts, y: int) -> float | None:
    """x on the wing's inner edge at height y (pts run bottom to top)."""
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        lo, hi = sorted((y1, y2))
        if lo <= y <= hi and y1 != y2:
            return x1 + (x2 - x1) * (y - y1) / (y2 - y1)
    return None


@lru_cache(maxsize=1)
def masks() -> dict[str, np.ndarray]:
    """Which pixels of the picture belong to the cap, the tassel and each wing."""
    rgba = np.asarray(owl.base()).astype(int)
    r, b, a = rgba[..., 0], rgba[..., 2], rgba[..., 3]
    blue = (b > r + 25) & (b > 60)                         # his feathers
    solid = a > 8
    yy, xx = np.mgrid[0:1024, 0:1024]
    gold = (r > 120) & (r - b > 70) & solid
    l, t, rr, bb = TASSEL_BOX
    in_tassel_box = (xx >= l) & (xx <= rr) & (yy >= t) & (yy <= bb)
    tassel = _dilate(gold & in_tassel_box, 7) & solid & ~blue & in_tassel_box
    inside = _poly_mask(CAP_OUTLINE)
    cap_core = inside & ~blue & solid & ~tassel
    cap = _dilate(cap_core, 9) & solid & ~blue & ~tassel & (yy < 335)
    out = {"cap": cap, "tassel": tassel}
    for side, outer, inner in (("wing_l", WING_OUTER, WING_INNER),
                               ("wing_r", _mirror_pts(WING_OUTER), _mirror_pts(WING_INNER))):
        poly = _poly_mask(outer + inner[1:])
        body_side = np.zeros_like(poly)
        for y in range(min(p[1] for p in inner), max(p[1] for p in inner) + 1):
            x = _edge_x(inner, y)
            if x is not None:
                if side == "wing_l":
                    body_side[y, int(math.ceil(x)):] = True
                else:
                    body_side[y, :int(x)] = True
        out[side] = _dilate(poly, 10) & solid & ~body_side & (yy > 520)
        out[side + "_band"] = out[side] & _dilate(body_side, 7)   # stays on the body under the wing's edge
        out[side + "_body"] = body_side
    return out


@lru_cache(maxsize=1)
def _head_top() -> Image.Image:
    """The top of his head, which the cap hides in the picture."""
    img = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = HEAD_TOP
    d.ellipse((x0 - 8, y0 - 8, x1 + 8, y1 + 8), fill=owl.RIM + (220,))
    d.ellipse((x0, y0, x1, y1), fill=INK + (255,))
    d.ellipse((x0 + 7, y0 + 7, x1 - 7, y1 - 7), fill=NAVY + (255,))
    # a soft highlight and a few feather strokes so it isn't a flat blob
    d.ellipse((x0 + 90, y0 + 24, x1 - 90, y0 + 120), fill=(48, 72, 124, 255))
    for k, x in enumerate(range(x0 + 120, x1 - 100, 60)):
        d.arc((x - 30, y0 + 40 + (k % 2) * 14, x + 30, y0 + 100 + (k % 2) * 14), 200, 340, fill=NAVY_DARK + (255,),
              width=5)
    return img.filter(ImageFilter.GaussianBlur(0.6))


@lru_cache(maxsize=256)
def body(shape: str = "X", blink: float = 0.0, gaze: int = 0) -> Image.Image:
    """Owlbert without his cap, tassel and folded wings, with a mouth shape, blink and gaze (-2..2)."""
    m = masks()
    face = owl.mouth_frame(shape, blink)
    if gaze:
        face = _look(face, gaze, blink)
    arr = np.asarray(face).copy()
    for k in ("cap", "tassel", "wing_l", "wing_r"):
        arr[m[k] & ~m.get(k + "_band", np.zeros_like(m[k]))] = 0
    # the side of his head behind the tassel: take it from the matching left side of the picture
    l, t, r, b = TASSEL_BOX
    mirror = np.asarray(owl.base())[:, ::-1].copy()
    mirror[m["cap"][:, ::-1]] = 0
    arr[t:b, l:r] = mirror[t:b, l:r]
    cut = Image.fromarray(arr, "RGBA")
    img = _head_top_clipped().copy()
    img.alpha_composite(cut)
    return img


@lru_cache(maxsize=1)
def _head_top_clipped() -> Image.Image:
    """The drawn head top, only where the cap or his head is (so it never peeks out around the cap)."""
    top = _head_top()
    keep = masks()["cap"] | (np.asarray(owl.base())[..., 3] > 8)
    a = np.asarray(top).copy()
    a[..., 3] = (a[..., 3] * keep).astype("uint8")
    return Image.fromarray(a, "RGBA")


@lru_cache(maxsize=1)
def _eye_white() -> tuple[int, int, int]:
    px = owl.base().getpixel((owl.EYES[0][0] - 82, owl.EYES[0][1] + 6))
    return px[:3]


def _look(img: Image.Image, gaze: int, blink: float) -> Image.Image:
    """Move the irises sideways inside the eye whites (gaze -2..2, negative = towards the viewer's left)."""
    if blink >= 0.99:
        return img
    dx = int(gaze * 11)
    out = img.copy()
    white = _eye_white() + (255,)
    for cx, cy in owl.EYES:
        r_iris = 70
        box = (cx - r_iris, cy - r_iris, cx + r_iris, cy + r_iris)
        iris = img.crop(box)
        disc = Image.new("L", iris.size, 0)
        ImageDraw.Draw(disc).ellipse((0, 0, iris.width - 1, iris.height - 1), fill=255)
        d = ImageDraw.Draw(out)
        d.ellipse(box, fill=white)
        clip = Image.new("L", out.size, 0)
        ImageDraw.Draw(clip).ellipse((cx - owl.EYE_R + 6, cy - owl.EYE_R + 6, cx + owl.EYE_R - 6, cy + owl.EYE_R - 6),
                                     fill=255)
        layer = Image.new("RGBA", out.size, (0, 0, 0, 0))
        layer.paste(iris, (box[0] + dx, box[1]), disc)
        layer.putalpha(Image.fromarray(np.minimum(np.asarray(layer.split()[3]), np.asarray(clip))))
        out.alpha_composite(layer)
    out.paste(owl.base(), (0, 0), owl._rims())   # glasses frames back on top
    return out


def _cut(key: str) -> Image.Image:
    arr = np.asarray(owl.base()).copy()
    arr[~masks()[key]] = 0
    return Image.fromarray(arr, "RGBA")


@lru_cache(maxsize=1)
def parts() -> dict[str, Part]:
    p = {"cap": _part(_cut("cap"), CAP_PIVOT), "tassel": _part(_cut("tassel"), TASSEL_PIVOT),
         "wing_l": _part(_cut("wing_l"), WING_PIVOT),
         "wing_r": _part(_cut("wing_r"), (1024 - WING_PIVOT[0], WING_PIVOT[1]))}
    spread = spread_wing()
    p["spread_l"] = Part(_premul(spread), (SPREAD_PIVOT[0] - SPREAD_ANCHOR[0], SPREAD_PIVOT[1] - SPREAD_ANCHOR[1]),
                         SPREAD_PIVOT)
    flipped = spread.transpose(Image.FLIP_LEFT_RIGHT)   # the wing only - Owlbert himself is never flipped
    rx = 1024 - SPREAD_PIVOT[0]
    p["spread_r"] = Part(_premul(flipped), (rx - (spread.width - SPREAD_ANCHOR[0]), SPREAD_PIVOT[1] - SPREAD_ANCHOR[1]),
                         (rx, SPREAD_PIVOT[1]))
    inside = cap_inside()
    p["cap_inside"] = Part(_premul(inside), (CAP_PIVOT[0] - inside.width / 2, CAP_PIVOT[1] - CAP_INSIDE_RIM),
                           CAP_PIVOT)
    return p


# ---------------------------------------------------------------- new drawings
SPREAD_ANCHOR = (385, 175)   # the shoulder inside the spread-wing drawing


def _smooth(pts, n=8):
    """A closed Catmull-Rom curve through the points."""
    out = []
    k = len(pts)
    for i in range(k):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % k], pts[(i + 2) % k]
        for j in range(n):
            t = j / n
            out.append(tuple(0.5 * ((2 * p1[c]) + (-p0[c] + p2[c]) * t + (2 * p0[c] - 5 * p1[c] + 4 * p2[c] - p3[c]) * t * t
                                    + (-p0[c] + 3 * p1[c] - 3 * p2[c] + p3[c]) * t ** 3) for c in (0, 1)))
    return out


def _feather(root, tip, width):
    """A long rounded feather from root to tip."""
    (x1, y1), (x2, y2) = root, tip
    ang = math.atan2(y2 - y1, x2 - x1)
    length = math.hypot(x2 - x1, y2 - y1)
    nx, ny = -math.sin(ang), math.cos(ang)
    pts = []
    for k in range(13):                       # one side, root to tip
        f = k / 12
        w = width * (0.75 + 0.25 * math.sin(math.pi * min(1.0, f * 1.2)))
        pts.append((x1 + (x2 - x1) * f + nx * w / 2, y1 + (y2 - y1) * f + ny * w / 2))
    for k in range(1, 8):                     # round tip
        a = ang + math.pi / 2 - math.pi * k / 8
        pts.append((x2 + math.cos(a) * width / 2 * 0.9, y2 + math.sin(a) * width / 2 * 0.9))
    for k in range(12, -1, -1):
        f = k / 12
        w = width * (0.75 + 0.25 * math.sin(math.pi * min(1.0, f * 1.2)))
        pts.append((x1 + (x2 - x1) * f - nx * w / 2, y1 + (y2 - y1) * f - ny * w / 2))
    return pts, length


@lru_cache(maxsize=1)
def spread_wing() -> Image.Image:
    """A left wing spread out for flying, drawn in Owlbert's colours (shoulder at SPREAD_ANCHOR)."""
    ss = 2
    W, H = 420, 290
    ax, ay = SPREAD_ANCHOR
    img = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def S(pts):
        return [((ax + x) * ss, (ay + y) * ss) for x, y in pts]

    # long flight feathers: tips make the scalloped back edge of the wing
    tips = [(-352, -96), (-344, -50), (-318, -8), (-278, 26), (-228, 50), (-172, 62), (-114, 64), (-58, 54)]
    roots = [(-232, -98), (-214, -78), (-192, -58), (-166, -42), (-136, -28), (-102, -18), (-68, -10), (-34, -4)]
    feathers = [_feather(r, t, 48 if k < 3 else 44)[0] for k, (r, t) in enumerate(zip(roots, tips))]
    for pts in feathers:
        d.polygon(S(_grow(pts, 7)), fill=owl.RIM + (225,))
    for pts in feathers:
        d.polygon(S(_grow(pts, 4)), fill=INK + (255,))
    for k, (pts, r, t) in enumerate(zip(feathers, roots, tips)):
        d.polygon(S(pts), fill=NAVY_LIGHT + (255,) if k % 2 == 0 else (50, 76, 132, 255))
        mid = (r[0] + (t[0] - r[0]) * 0.85, r[1] + (t[1] - r[1]) * 0.85)
        d.line(S([r, mid]), fill=NAVY_DARK + (255,), width=3 * ss)
    # the arm of the wing (covert feathers) over the roots of the long feathers
    arm = _smooth([(26, -6), (4, -58), (-60, -104), (-142, -132), (-224, -136), (-282, -118), (-296, -92),
                   (-262, -66), (-200, -40), (-130, -14), (-62, 6), (-8, 30)], 10)
    d.polygon(S(_grow(arm, 7)), fill=owl.RIM + (225,))
    d.polygon(S(_grow(arm, 4)), fill=INK + (255,))
    d.polygon(S(arm), fill=NAVY + (255,))
    d.polygon(S(_smooth([(0, -50), (-60, -96), (-142, -122), (-222, -126), (-250, -112), (-150, -96),
                         (-70, -66), (-10, -26)], 8)), fill=(46, 70, 124, 255))
    for row, (y0, x_from, x_to) in enumerate(((-96, -250, -60), (-58, -200, -20))):
        for x in range(x_from, x_to, 40):
            yy = y0 + (x - x_from) * 0.32 if row == 0 else y0 + (x - x_from) * 0.25
            d.arc((S([(x - 22, yy - 14)])[0][0], S([(x - 22, yy - 14)])[0][1],
                   S([(x + 22, yy + 22)])[0][0], S([(x + 22, yy + 22)])[0][1]), 20, 160,
                  fill=NAVY_DARK + (255,), width=4 * ss)
    return img.resize((W, H), Image.LANCZOS)


def _grow(pts, r):
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    out = []
    for x, y in pts:
        dx, dy = x - cx, y - cy
        n = math.hypot(dx, dy) or 1
        out.append((x + dx / n * r, y + dy / n * r))
    return out


CAP_INSIDE_RIM = 70   # y of the opening's centre inside the cap_inside drawing


@lru_cache(maxsize=1)
def cap_inside() -> Image.Image:
    """The cap turned over (opening up), as he holds it to pull something out."""
    ss = 2
    W, H = 700, 260
    img = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    def S(pts):
        return [(x * ss, y * ss) for x, y in pts]

    cx, rim = W // 2, CAP_INSIDE_RIM
    # the board, nearly edge-on, at the bottom
    board = [(cx - 330, 178), (cx + 330, 178), (cx + 344, 206), (cx - 344, 206)]
    d.polygon(S(_grow(board, 7)), fill=owl.RIM + (230,))
    d.polygon(S(board), fill=(22, 22, 24, 255), outline=INK + (255,))
    d.line(S([(cx - 330, 180), (cx + 330, 180)]), fill=(96, 96, 100, 255), width=4 * ss)
    # the bowl of the cap, wider at the top
    bowl = [(cx - 175, rim), (cx + 175, rim), (cx + 150, 182), (cx - 150, 182)]
    d.polygon(S(_grow(bowl, 7)), fill=owl.RIM + (230,))
    d.polygon(S(bowl), fill=(34, 33, 35, 255))
    d.polygon(S([(cx - 40, rim + 10), (cx + 60, rim + 10), (cx + 52, 176), (cx - 36, 176)]), fill=(52, 51, 54, 255))
    d.line(S([(cx - 172, rim + 22), (cx + 172, rim + 22)]), fill=GOLD + (255,), width=6 * ss)
    # the opening
    d.ellipse(S([(cx - 182, rim - 34), (cx + 182, rim + 34)]), fill=INK + (255,))
    d.ellipse(S([(cx - 170, rim - 26), (cx + 170, rim + 26)]), fill=(8, 8, 12, 255))
    d.ellipse(S([(cx - 150, rim - 12), (cx + 150, rim + 22)]), fill=(26, 20, 34, 255))
    return img.resize((W, H), Image.LANCZOS)


# ---------------------------------------------------------------- posing and drawing
FEET_Y = 922          # bottom of his feet (squash keeps these on the ground)
ANCHOR = (512, 600)   # the middle of his body: he turns and banks around this


@dataclass
class Pose:
    """Everything that can move. Angles are in degrees; "outward" lifts a wing away from his body."""
    x: float = 0.0                 # screen position of ANCHOR
    y: float = 0.0
    rot: float = 0.0               # whole-body bank, positive = leaning to the viewer's left
    squash: float = 0.0            # + squashes (landing), - stretches (take-off)
    shape: str = "X"               # mouth (Rhubarb letter)
    blink: float = 0.0
    gaze: int = 0                  # -2 (look to the viewer's left) .. 2
    wing_l: float = 0.0            # folded wings lifted outward
    wing_r: float = 0.0
    spread: float = 0.0            # 0 = wings folded, 1 = wings spread for flying
    flap_l: float = 0.0            # spread wings, positive = up
    flap_r: float = 0.0
    cap_dx: float = 0.0            # cap position relative to his head (art pixels)
    cap_dy: float = 0.0
    cap_rot: float = 0.0
    cap_flip: float = 0.0          # 0 = on his head the right way up, 1 = turned over (opening up)
    tassel: float = 0.0            # tassel swing


def _rot(angle_deg: float, cx: float, cy: float) -> np.ndarray:
    """3x3 rotation about (cx, cy) in screen convention (positive = anticlockwise on screen, like OpenCV)."""
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, s, cx - c * cx - s * cy], [-s, c, cy + s * cx - c * cy], [0, 0, 1]], dtype=np.float64)


def _move(dx: float, dy: float) -> np.ndarray:
    return np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1]], dtype=np.float64)


def _scale(sx: float, sy: float, cx: float = 0.0, cy: float = 0.0) -> np.ndarray:
    return np.array([[sx, 0, cx - sx * cx], [0, sy, cy - sy * cy], [0, 0, 1]], dtype=np.float64)


@lru_cache(maxsize=64)
def _scaled_part(name: str, s: float) -> Part:
    p = parts()[name]
    h, w = p.img.shape[:2]
    nw, nh = max(1, round(w * s)), max(1, round(h * s))
    img = to_image(p.img).resize((nw, nh), Image.LANCZOS)    # Pillow handles the alpha edges itself
    return Part(_premul(img), p.origin, p.pivot)


@lru_cache(maxsize=256)
def _scaled_body(shape: str, blink: float, gaze: int, s: float) -> Part:
    small = body(shape, blink, gaze).resize((round(1024 * s), round(1024 * s)), Image.LANCZOS)
    return Part(_premul(small), (0, 0), ANCHOR)


class Stage:
    """Draws posed Owlbert onto transparent full frames of a given size, at the corner presenter's size."""

    def __init__(self, width: int, height: int, scale: float | None = None):
        import cv2   # noqa: F401 - fail early with a clear import error
        self.w, self.h = width, height
        x, y, pw, ph = owl.home_box(width, height)
        bx0, by0, bx1, by1 = owl.base().getbbox()
        self.s = round(scale or ph / (by1 - by0), 4)
        self.home = (x + (ANCHOR[0] - bx0) * self.s, y + (ANCHOR[1] - by0) * self.s)
        self.box = (x, y, pw, ph)
        self.inward = -1 if x + pw / 2 > width / 2 else 1     # towards the middle of the screen

    def rest(self) -> Pose:
        return Pose(x=self.home[0], y=self.home[1])

    # art -> screen for a pose
    def to_screen(self, pose: Pose) -> np.ndarray:
        s = self.s
        sy = 1.0 - pose.squash
        sx = 1.0 + pose.squash * 0.6
        lift = (FEET_Y - ANCHOR[1]) * s * (1 - sy)      # keep the feet down when squashing
        m = _move(pose.x, pose.y + lift) @ _rot(pose.rot, 0, 0) @ _scale(sx * s, sy * s) @ _move(-ANCHOR[0], -ANCHOR[1])
        return m

    def cap_matrix(self, pose: Pose) -> tuple[np.ndarray, bool]:
        """Art -> art movement of the cap, and whether it's showing its inside."""
        flip = pose.cap_flip
        sy = max(0.04, abs(math.cos(math.pi * flip)))
        px, py = CAP_PIVOT
        m = _move(pose.cap_dx, pose.cap_dy) @ _rot(pose.cap_rot, px, py) @ _scale(1.0, sy, px, py)
        return m, flip > 0.5

    def tassel_pivot(self, pose: Pose) -> tuple[float, float]:
        """Where the tassel hangs from, in art coordinates (follows the cap)."""
        m, inside = self.cap_matrix(pose)
        pt = (CAP_PIVOT[0] + 330, CAP_PIVOT[1] - CAP_INSIDE_RIM + 192) if inside else TASSEL_PIVOT
        v = m @ np.array([pt[0], pt[1], 1.0])
        return float(v[0]), float(v[1])

    def layers(self, pose: Pose) -> list[tuple[Part, np.ndarray, float]]:
        """(part at this scale, part pixel -> art matrix, opacity) back to front."""
        s = self.s
        out: list[tuple[Part, np.ndarray, float]] = []

        def add(part: Part, art_move: np.ndarray, alpha: float = 1.0):
            if alpha <= 0.01:
                return
            px2art = _move(*part.origin) @ _scale(1 / s, 1 / s)
            out.append((part, art_move @ px2art, alpha))

        spread = max(0.0, min(1.0, pose.spread))
        if spread > 0:
            for name, ang in (("spread_l", -pose.flap_l), ("spread_r", pose.flap_r)):
                p = _scaled_part(name, s)
                grow = 0.35 + 0.65 * spread
                add(p, _rot(ang, *p.pivot) @ _scale(grow, 0.6 + 0.4 * spread, *p.pivot), min(1.0, spread * 2.5))
        add(_scaled_body(pose.shape, round(pose.blink * 4) / 4, int(pose.gaze), s), np.eye(3))
        fold = 1.0 - min(1.0, spread * 2.0)
        if fold > 0:
            for name, ang in (("wing_l", -pose.wing_l), ("wing_r", pose.wing_r)):
                p = _scaled_part(name, s)
                add(p, _rot(ang, *p.pivot), fold)
        cap_m, inside = self.cap_matrix(pose)
        add(_scaled_part("cap_inside" if inside else "cap", s), cap_m)
        tp = _scaled_part("tassel", s)
        ax, ay = self.tassel_pivot(pose)
        add(tp, _move(ax - TASSEL_PIVOT[0], ay - TASSEL_PIVOT[1]) @ _rot(pose.tassel + (pose.cap_rot if not inside
                                                                                         else 0), *TASSEL_PIVOT))
        return out

    def draw(self, pose: Pose, frame: np.ndarray | None = None) -> np.ndarray:
        """Draw onto a premultiplied float32 RGBA frame (h, w, 4); returns it."""
        import cv2
        if frame is None:
            frame = np.zeros((self.h, self.w, 4), np.float32)
        to_screen = self.to_screen(pose)
        for part, m, alpha in self.layers(pose):
            full = to_screen @ m
            ph, pw = part.img.shape[:2]
            corners = full @ np.array([[0, pw, 0, pw], [0, 0, ph, ph], [1, 1, 1, 1]], dtype=np.float64)
            x0 = max(0, int(math.floor(corners[0].min())) - 1)
            y0 = max(0, int(math.floor(corners[1].min())) - 1)
            x1 = min(self.w, int(math.ceil(corners[0].max())) + 2)
            y1 = min(self.h, int(math.ceil(corners[1].max())) + 2)
            if x1 <= x0 or y1 <= y0:
                continue
            roi_m = (_move(-x0, -y0) @ full)[:2].astype(np.float32)
            src = cv2.warpAffine(part.img, roi_m, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
            if alpha < 1:
                src *= alpha
            dst = frame[y0:y1, x0:x1]
            dst *= 1.0 - src[..., 3:4]
            dst += src
        return frame


def to_image(frame: np.ndarray) -> Image.Image:
    """Premultiplied float frame -> ordinary RGBA picture."""
    a = frame[..., 3:4]
    rgb = np.where(a > 1e-4, frame[..., :3] / np.maximum(a, 1e-4), 0)
    out = np.concatenate([np.clip(rgb, 0, 1), np.clip(a, 0, 1)], axis=2)
    return Image.fromarray((out * 255 + 0.5).astype("uint8"), "RGBA")


def from_image(img: Image.Image) -> np.ndarray:
    return _premul(img)
