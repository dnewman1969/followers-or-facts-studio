"""Video styles: the same facts, told and drawn in different ways.

Every style keeps the same factual skeleton (fact first, the myth shown once and marked as a claim,
how the lie was built, the trick named, the real story, the fact again). A style changes Owlbert's
tone, the pacing, how long each shot holds, and the picture recipe for the image and video models.

The styles live in data/styles.json (from the research "Art styles caricatures and hybrids"): the 12
house styles plus about 70 looks from animation, film and TV history, puppets and stop motion, print and
poster art, fine art, storybooks and art from around the world. Each is described by its traits only:
'inspired_by' names the historical inspiration for you and never goes into a prompt.

New looks start as "draft" (untested). The style test (Storyboard → Test styles) paints each one on your
PC; you press Keep or Drop, and that's saved in <data>/style-ratings.json. Dropped looks leave the
pickers. Style mixes (key "mix:<name>") come from data/hybrids.json or the mixer (styleengine.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).parent / "data"
DEFAULT = "documentary"


@dataclass(frozen=True)
class Style:
    key: str
    name: str
    blurb: str                 # one line for the picker
    tone: str                  # for the writer
    wpm: int                   # Owlbert's narration speed in this style (words per minute)
    shot_seconds: float        # average time each picture stays on screen
    look: str                  # picture recipe: the medium first (the image model reads early words hardest)
    negative: str = ""         # (old; the turbo image model ignores negatives, see 'clean')
    motion: str = ""           # added to animation prompts
    owl_look: str = ""         # how Owlbert's scenes are staged
    sample: str = ""           # a short original passage in this style, for the writer to match
    humor: int = 1             # 0 none ... 3 lots (always 0 on careful topics)
    caricature: bool = False   # may show cartoon caricatures of the public figures who sold the lie
    cartoon: bool = False      # clearly not photographic (required for caricatures)
    shot_types: tuple[str, ...] = ("broll", "owl", "detail")
    clean: str = ""            # what keeps the picture clean, said as something to draw (no "no ..." words)
    status: str = "live"       # live (house style) | draft (untested) | kept | dropped
    tier: str = "A"            # A signature, B occasional, C special use, care (needs your OK)
    group: str = "house"
    medium: str = ""
    motion_class: str = "parallax"   # parallax | stepped (stop-motion: held frames, jitter)
    careful_ok: bool = False   # sober enough for careful topics (victims)
    info: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)  # era, inspired_by, Dave's format

    @property
    def needs_ok(self) -> str:
        """Why this look needs your OK before use (cultural or political), or ""."""
        return self.info.get("cultural") or (self.info.get("note") if self.info.get("political") else "")


FIELDS = {f for f in Style.__dataclass_fields__}  # type: ignore[attr-defined]


def _style(d: dict[str, Any]) -> Style:
    known = {k: v for k, v in d.items() if k in FIELDS and k != "info"}
    known["shot_types"] = tuple(known.get("shot_types") or ("broll", "owl", "detail"))
    extra = {k: v for k, v in d.items() if k not in FIELDS}
    return Style(**known, info=extra)


@lru_cache(maxsize=1)
def _all() -> dict[str, Style]:
    data = json.loads((DATA / "styles.json").read_text(encoding="utf-8"))
    return {d["key"]: _style(d) for d in data["styles"]}


STYLES: dict[str, Style] = dict(_all())


def ratings_path() -> Path:
    from .config import data_dir
    return data_dir() / "style-ratings.json"


def ratings() -> dict[str, str]:
    """Your Keep / Drop choices from the style test: {style key: "kept" | "dropped"}."""
    try:
        return json.loads(ratings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def rate(key: str, verdict: str) -> None:
    if verdict not in ("kept", "dropped", "draft"):
        raise ValueError(verdict)
    r = ratings()
    if verdict == "draft":
        r.pop(key, None)
    else:
        r[key] = verdict
    p = ratings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(r, indent=1), encoding="utf-8")


def status_of(s: Style) -> str:
    return ratings().get(s.key, s.status) if s.status != "live" else "live"


def get(key: str | None) -> Style:
    key = key or DEFAULT
    if key.startswith("mix:"):
        from . import styleengine
        built = styleengine.build(key)
        if built:
            return built
    return STYLES.get(key, STYLES[DEFAULT])


def choices(careful: bool = False, include_drafts: bool = True) -> list[tuple[str, str]]:
    """(key, label) for the pickers: house styles, then kept looks, then untested ones (marked), then mixes.
    Dropped looks and 'care' looks you haven't OK'd stay out; careful topics only get sober looks."""
    rate_of = ratings()
    rows: list[tuple[int, str, str]] = []
    for s in STYLES.values():
        st = rate_of.get(s.key, s.status) if s.status != "live" else "live"
        if st == "dropped" or (careful and not s.careful_ok) or (st == "draft" and not include_drafts):
            continue
        label = s.name + (" (untested)" if st == "draft" else "") + \
            (" (needs your OK)" if s.tier == "care" and st != "kept" else "")
        rows.append(({"live": 0, "kept": 1}.get(st, 2), label, s.key))
    out = [(k, label) for _, label, k in sorted(rows)]
    from . import styleengine
    for h in styleengine.recipes():
        if careful and not h["careful_ok"]:
            continue
        if rate_of.get(f"mix:{h['key']}") == "dropped":
            continue
        out.append((f"mix:{h['key']}", f"Mix: {h['name']}" + ("" if rate_of.get(f"mix:{h['key']}") == "kept"
                                                              else " (untested)")))
    return out


def describe(s: Style) -> str:
    """Dave's format, for the tooltip and the style test sheet."""
    i = s.info
    rows = [("Era", i.get("era")), ("Inspired by (never in prompts)", i.get("inspired_by")),
            ("Visual DNA", i.get("visual_dna")), ("Character design", i.get("character_design")),
            ("Linework", i.get("linework")), ("Colour palette", i.get("color_palette")),
            ("Background", i.get("background_style")), ("Animation", i.get("animation_style")),
            ("Lighting", i.get("lighting_style")), ("Best uses", i.get("best_uses")),
            ("Prompt elements", ", ".join(i.get("prompt_elements") or [])), ("Needs care", s.needs_ok)]
    return "\n".join(f"{k}: {v}" for k, v in rows if v)
