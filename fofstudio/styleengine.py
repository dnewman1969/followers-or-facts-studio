"""Style Evolution Engine: mixes two looks into a new one, and keeps the channel from looking samey.

From the research "Art styles caricatures and hybrids":
  * a mix takes the BODY (how it's made: medium, line, texture, proportions, motion) from one look and the
    WORLD (where it lives: colours, light, setting, era) from another. Only one medium, one light, one
    palette and one set of proportions, or the picture turns to mush;
  * clash rules refuse mixes that can't work: two proportion systems (life-like traced figures with tiny
    big-head ones), anything not sober on a careful topic, politically coded looks as the channel's own voice,
    and looks that need your OK (cultural care) unless you've kept them;
  * the prompt stays short (the turbo image model reads 3-5 ideas well): the medium phrase first, then the
    world, and genre words are turned into what you'd see ("cyberpunk" -> neon rim light and rain);
  * the fatigue score (0 = fresh, 1 = worn out) compares a look with the last 8 videos: the same medium and
    palette count double, older videos count less (0.8 per video back). Above 0.6 it's flagged and the
    recommender suggests fresher looks, plus "due" families you haven't used in 8 videos.
Scores are plain counting, the same answer every time. The picture-similarity part of the research's score
needs an image-style model whose licence isn't confirmed yet, so it isn't used.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .util import StageError

DATA = Path(__file__).parent / "data"
WORLD_WORDS = re.compile(r"\b(colou?rs?|palette|tones?|hues?|light|lit|lighting|glow\w*|shadows?|backlit|sky|night|dusk|"
                         r"dawn|sunset|moon\w*|rain|fog|haze|mist|neon|amber|teal|blue|red|gold|black|white|cream|"
                         r"sepia|pastel|ochre|green|purple|orange|background|backdrop|city|street|room|office|town|"
                         r"forest|village|harbou?r|set|era|\d{4}s|century|victorian|retro|futur\w*)\b", re.I)
GENRE_TO_SIGHT = {"cyberpunk": "neon rim light, rain-slick night streets, glowing signs",
                  "noir": "low-key light, slatted shadows, rain on glass",
                  "horror": "green moonlight, cartoon cobwebs, crooked shapes, playful not scary",
                  "space opera": "painted starfield, gleaming starship interiors",
                  "steampunk": "brass gears, boilers and steam, gaslight",
                  "science fiction": "retro-futurist rockets and satellites",
                  "sci-fi": "retro-futurist rockets and satellites"}
PROPORTIONS = {"chibi": "tiny", "super_deformed": "tiny", "rotoscope": "lifelike", "traced": "lifelike"}
DUE_FAMILIES = {
    "woodcut": ["relief_print", "mix:woodcut_ledger"], "ink wash": ["ink_wash", "mix:ink_wash_detective"],
    "charcoal": ["charcoal", "mix:charcoal_courtroom"],
    "retro print posters": ["new_deal_public_works", "risograph_zine_print", "mix:duotone_cold_war_poster"],
    "stop motion": ["fingerprint_clay_stop_motion", "needle_felt_stop_motion", "armature_puppet_stop_motion"],
    "marionettes": ["old_world_string_marionette", "mix:marionette_medicine_show"],
    "felt puppets": ["felt_variety_show_hand", "mix:felt_puppet_fact_lab"],
    "paper cut-out": ["papercut", "victorian_toy_theatre", "mix:paper_diorama_newsroom"],
    "silhouette": ["backlit_shadow_puppet_fable", "mix:shadow_theatre_folklore"],
    "storybook": ["golden_age_storybook", "textured_picture_book", "mix:storybook_maritime"],
    "painted backgrounds": ["mix:gouache_ghost_town_western", "saturday_morning_limited_tv"],
    "mixed media": ["mixed_media_collage", "mix:mixed_media_scrapbook"],
}
FATIGUE_LIMIT = 0.6
HISTORY_N = 8


@lru_cache(maxsize=1)
def recipes() -> list[dict[str, Any]]:
    return json.loads((DATA / "hybrids.json").read_text(encoding="utf-8"))["hybrids"]


def recipe(key: str) -> dict[str, Any] | None:
    return next((h for h in recipes() if h["key"] == key), None)


def _sight(text: str) -> str:
    for genre, sight in GENRE_TO_SIGHT.items():
        text = re.sub(rf"\b{genre}\b", sight, text, flags=re.I)
    return text


MATERIAL_WORDS = re.compile(r"\b(paper|ink|brush|wash|texture|grain|line|lines|outline|stroke|print|carved|"
                            r"gouge|felt|clay|wool|stitch\w*|thumbprints?|pigment|canvas|cel|halftone|crosshatch\w*)\b",
                            re.I)


def split_layers(elements: list[str]) -> tuple[list[str], list[str]]:
    """A look's prompt elements, sorted into BODY (how it's made) and WORLD (colours, light, setting)."""
    body, world = [], []
    for e in elements:
        (world if WORLD_WORDS.search(e) and not MATERIAL_WORDS.search(e) else body).append(e)
    return body, world


def _voice_for(medium: str, text: str, careful: bool) -> str:
    low = text.lower()
    if careful:
        return "grave"
    if any(w in low for w in ("noir", "detective", "shadow", "night", "courtroom")):
        return "suspense"
    if medium in ("puppet", "felt", "clay", "cel", "cut_paper", "object", "textile"):
        return "playful"
    if "storybook" in low or medium in ("paint",):
        return "warm"
    return "wry"


VOICES = {  # how Owlbert sounds in a mix (same wording as the style database's voices)
    "grave": ("Grave and measured. Owlbert speaks quietly and lets the evidence carry the weight.", 138, 5.5, 0),
    "warm": ("Warm and storybook-gentle. Owlbert tells it like a careful tale, with everyday examples.", 145, 5.0, 1),
    "playful": ("Curious and playful. One big picture carries the idea; quick, clear and friendly.", 155, 4.0, 2),
    "wry": ("Wry and sharp, punching up at the sellers only; every joke is followed by the plain sourced fact.",
            155, 4.0, 2),
    "suspense": ("Hushed and suspenseful. Owlbert opens the file and walks the evidence in order.", 140, 5.0, 0),
}


def _make(key: str, name: str, body: str, world: str, palette: str, medium: str, motion_class: str, careful: bool,
          caricature: bool, owl: str, motion: str, info: dict[str, Any]):
    from .styles import STYLES, Style
    voice = _voice_for(medium, f"{body} {world}", careful)
    tone, wpm, shot, humor = VOICES[voice]
    sample = next((s.sample for s in STYLES.values() if s.info.get("voice") == voice), STYLES["documentary"].sample)
    look = ", ".join(x for x in (body, _sight(world), palette and f"{palette.lower()} palette") if x) + ", 16:9"
    return Style(key=key, name=name, blurb=f"{body} / {world}"[:140], tone=tone, wpm=wpm, shot_seconds=shot,
                 look=look, motion=motion or ("held frames on twos, slight handmade jitter" if motion_class == "stepped"
                                               else "slow parallax drift between layers"),
                 owl_look=owl or f"Owlbert made in the same way: {body.split(',')[0].lower()}",
                 sample=sample, humor=0 if careful else humor, caricature=caricature, cartoon=True,
                 shot_types=("broll", "owl", "metaphor") + (("caricature",) if caricature else ()),
                 clean="clearly hand-made, clean uncluttered composition, wordless surfaces",
                 status="draft", tier="B", group="mix", medium=medium, motion_class=motion_class,
                 careful_ok=careful, info={"voice": voice, **info})


def build(key: str):
    """The Style for a mix key: 'mix:<recipe>' or 'mix:<body look>+<world look>'."""
    name = key[4:]
    r = recipe(name)
    if r:
        return _make(key, r["name"], r["body"], r["world"], r.get("palette", ""), r["medium"], r["motion_class"],
                     r["careful_ok"], r.get("caricature_ok", False), r.get("owlbert", ""), r.get("motion", ""),
                     {"inspired_by": r.get("inspired_by", ""), "fit": r.get("fit", ""), "risk": r.get("risk", ""),
                      "recipe": True})
    if "+" in name:
        a, b = name.split("+", 1)
        try:
            return mix(a, b)
        except StageError:
            return None
    return None


def clashes(body_key: str, world_key: str, careful: bool = False) -> list[str]:
    """Why these two looks can't be mixed (empty = they can)."""
    from .styles import STYLES, ratings
    a, b = STYLES.get(body_key), STYLES.get(world_key)
    if not a or not b:
        return ["unknown look"]
    out = []
    if a.key == b.key:
        out.append("a look can't be mixed with itself")
    pa = next((v for k, v in PROPORTIONS.items() if k in a.key), "")
    pb = next((v for k, v in PROPORTIONS.items() if k in b.key), "")
    if pa and pb and pa != pb:
        out.append("two kinds of body proportions (life-like and tiny big-head) fight each other")
    if careful and not (a.careful_ok and b.careful_ok):
        out.append("this is a careful topic: only sober looks")
    for s in (a, b):
        if s.info.get("political"):
            out.append(f"{s.name} is politically coded: it can show propaganda, not be the channel's voice")
        if s.tier == "care" and ratings().get(s.key) != "kept":
            out.append(f"{s.name} needs your OK first (Test styles → Keep): {s.needs_ok}")
        if ratings().get(s.key) == "dropped":
            out.append(f"you dropped {s.name}")
    return out


def mix(body_key: str, world_key: str, careful: bool = False):
    """A new look: how it's made from one, where it lives from the other."""
    from .styles import STYLES
    problems = clashes(body_key, world_key, careful)
    if problems:
        raise StageError("Can't mix these: " + "; ".join(problems))
    a, b = STYLES[body_key], STYLES[world_key]
    elems_a = [e for e in (a.info.get("prompt_elements") or a.look.split(", ")) if e.strip() != "16:9"]
    body, _ = split_layers(elems_a)
    _, world = split_layers(list(b.info.get("prompt_elements") or b.look.split(", ")))
    body = ([elems_a[0]] + [x for x in body if x != elems_a[0]])[:3]   # the medium phrase always leads
    if len(world) < 2 and b.info.get("color_palette"):   # fill the world from the look's colour notes
        world.append(re.split(r"[;.]", b.info["color_palette"])[0][:80])
    world = world[:3] or [b.look.split(",")[0]]
    return _make(f"mix:{a.key}+{b.key}", f"{a.name} × {b.name}", ", ".join(body), ", ".join(world), "",
                 a.medium, a.motion_class, careful and a.careful_ok and b.careful_ok,
                 a.caricature and b.cartoon, a.owl_look, a.motion, {"body_parent": a.key, "world_parent": b.key})


# ------------------------------------------------------------------ fatigue across videos
def layers(style) -> dict[str, str]:
    """What a look is made of, for comparing videos: medium, palette words, light, group."""
    text = style.look.lower()
    palette = sorted(set(re.findall(r"\b(black and white|monochrome|sepia|neon|pastel|gold|teal|amber|red|blue|"
                                    r"green|purple|orange|cream|ochre)\b", text)))[:3]
    light = next((w for w in ("backlit", "low-key", "spotlight", "moonlight", "golden", "neon", "candle", "daylight",
                              "studio", "fog", "noir") if w in text), "")
    return {"medium": style.medium or "", "palette": "+".join(palette), "light": light, "group": style.group or ""}


WEIGHTS = {"medium": 2.0, "palette": 2.0, "light": 1.0, "group": 1.0}


def history(exclude: str = "") -> list[str]:
    """The styles of the most recent videos (newest first), not counting this one."""
    from .episode import Episode, list_episodes
    out = []
    for row in list_episodes():
        if row["project_id"] == exclude:
            continue
        try:
            key = (Episode.load(row["project_id"]).info.get("creative") or {}).get("style")
        except Exception:  # noqa: BLE001 - an unreadable old project just doesn't count
            continue
        if key:
            out.append(key)
        if len(out) >= HISTORY_N:
            break
    return out


def fatigue(key: str, recent: list[str]) -> float:
    """0 = fresh, 1 = worn out: how much this look repeats the last videos (newest weighs most)."""
    from .styles import get
    if not recent:
        return 0.0
    mine = layers(get(key))
    total = sum(WEIGHTS.values())
    score = norm = 0.0
    for k, other_key in enumerate(recent[:HISTORY_N]):
        decay = 0.8 ** k
        other = layers(get(other_key))
        same = 1.0 if other_key == key else sum(
            w for f, w in WEIGHTS.items() if mine[f] and mine[f] == other[f]) / total
        score += decay * same
        norm += decay
    return round(min(1.0, 1.6 * score / norm), 2) if norm else 0.0


def due(recent: list[str]) -> list[str]:
    """Families of looks you haven't used in the last 8 videos."""
    used = set(recent)
    return [fam for fam, keys in DUE_FAMILIES.items() if not used & set(keys)]


def recommend(recent: list[str], careful: bool = False, n: int = 5) -> list[tuple[str, float, str]]:
    """Fresh looks to try next: (key, fatigue, why), skipping dropped and not-yet-OK'd looks."""
    from .styles import choices
    pool = [k for k, label in choices(careful) if "needs your OK" not in label]
    due_keys = {k for fam in due(recent) for k in DUE_FAMILIES[fam]}
    scored = []
    for k in pool:
        f = fatigue(k, recent)
        bonus = 0.15 if k in due_keys else 0.0
        scored.append((round(f - bonus, 3), k, f))
    scored.sort()
    out = []
    for _, k, f in scored[:n]:
        why = "a family you haven't used lately" if k in due_keys else "little in common with your recent videos"
        out.append((k, f, why))
    return out
