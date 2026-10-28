"""Virtual Director: the quality gate between the storyboard's shot plan and the painting.

Dave's brief (2026-10-28): "The Story Writer decides what happens. You decide how it is shown." Before any
picture is painted, every shot is looked at against the shots before it (N-1 to N-5 and N-10) for location,
shot type, angle, camera move, pose, lighting, colour palette and setting, and given a similarity score:
90-100% = REJECT, 70-89% = REPAIR, under 70% = APPROVE. Pattern rules on top: never 3 close-ups in a row,
4 medium shots, 4 identical angles, 5 static shots, the same move 3 times; location, pose, lighting and
colour fatigue; and pacing (no long run of high-intensity shots, no flat line).

How it works:
  * the scores and rules are worked out by the program (plain counting, the same answer every time), not by
    an AI's opinion;
  * a shot that fails goes to the director AI (job "director") with what's wrong and what was used
    recently, to rewrite how it's SHOWN (camera, composition, light, move, pose, mood). What the shot shows
    and why (its story function) stays;
  * continuity beats variety: a rewrite that moves to a place the scene never mentions, or flips day to
    night inside a scene, is turned down and the old shot kept;
  * if the AI can't fix it, the program rotates the framing itself (a shot type, angle and move not used
    just before), which always breaks the copy;
  * your own ideas (Remake with new words) are scored but never rewritten;
  * the editorial guards still apply: no real names, no readable text, careful topics stay sober.
The review is saved as director-review.json / director-review.md and shown on the Storyboard page; each
shot gets APPROVED, REPAIRED or REJECTED. A shot still REJECTED blocks approval until you change or untick it.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from .config import settings
from .util import StageError

SHOT_TYPES = ["establishing", "wide", "medium", "close-up", "extreme close-up", "two shot", "over-the-shoulder",
              "pov", "bird's eye", "worm's eye", "dutch angle", "tracking", "dolly", "crane", "reaction",
              "silhouette"]
FAMILY = {"establishing": "wide", "wide": "wide", "bird's eye": "wide", "crane": "wide", "medium": "medium",
          "two shot": "medium", "over-the-shoulder": "medium", "tracking": "medium", "dolly": "medium",
          "close-up": "close", "extreme close-up": "close", "reaction": "close", "pov": "pov",
          "worm's eye": "low", "dutch angle": "tilted", "silhouette": "silhouette"}
CLOSE_UPS = {"close-up", "extreme close-up"}
ANGLES = ["eye level", "high angle", "low angle", "overhead", "ground level", "tilted"]
MOVES = ["static", "pan", "tilt", "dolly in", "dolly out", "crane", "orbit", "push-in", "pull-out", "handheld",
         "tracking", "steadicam", "drone"]
POSES = ["none", "standing", "walking", "running", "driving", "sitting", "climbing", "leaning", "kneeling",
         "holding objects", "pointing", "working", "interacting", "observing", "exploring", "talking"]
LIGHTS = ["natural daylight", "golden hour", "sunset", "moonlight", "storm", "fog", "cinematic studio", "neon",
          "harsh shadows", "low key noir", "firelight", "candlelight", "industrial lighting"]
PALETTES = ["blue", "orange", "green", "purple", "gold", "red", "monochrome", "sepia", "neon", "pastel"]
TIME_OF_DAY = {"natural daylight": "day", "golden hour": "day", "sunset": "day", "moonlight": "night",
               "candlelight": "night", "firelight": "night", "neon": "night"}
CAREFUL_OUT = {"dutch angle", "neon", "pastel", "handheld"}   # sober framing on careful topics

WEIGHTS = {"location": 15, "shot_type": 15, "angle": 10, "movement": 8, "pose": 10, "lighting": 10,
           "palette": 10, "environment": 22}
HISTORY = ((1, 1.0), (2, 1.0), (3, 0.95), (4, 0.9), (5, 0.9), (10, 0.8))
REJECT_AT, REPAIR_AT = 90, 70
HARD = ("close-ups", "medium", "angle", "static", "move")      # camera rules: must be fixed
# location, pose, lighting, colour and pacing are worth fixing, but continuity may keep them

# camera move -> the render's camera (engines.render.CAMERA_MOVES) and words for the animation model
MOVE_TO_CAMERA = {"static": "static", "pan": "pan_right", "tilt": "pan_up", "dolly in": "dolly_in",
                  "dolly out": "zoom_out", "crane": "pan_up", "orbit": "pan_left", "push-in": "zoom_in",
                  "pull-out": "zoom_out", "handheld": "zoom_in", "tracking": "pan_left", "steadicam": "dolly_in",
                  "drone": "zoom_out"}
MOVE_WORDS = {"static": "locked-off camera, only the scene moves", "pan": "the camera pans slowly sideways",
              "tilt": "the camera tilts slowly upward", "dolly in": "the camera dollies slowly forward",
              "dolly out": "the camera dollies slowly back", "crane": "the camera rises slowly like a crane",
              "orbit": "the camera orbits slowly around the subject", "push-in": "a slow push-in",
              "pull-out": "a slow pull-out that reveals more of the place", "handheld": "a slight handheld drift",
              "tracking": "the camera tracks alongside the subject", "steadicam": "a smooth gliding steadicam move",
              "drone": "a high aerial drift"}

_SHOT_WORDS = [("extreme close", "extreme close-up"), ("establishing", "establishing"),
               ("close-up", "close-up"), ("close up", "close-up"), ("closeup", "close-up"),
               ("over-the-shoulder", "over-the-shoulder"), ("over the shoulder", "over-the-shoulder"),
               ("point of view", "pov"), ("pov", "pov"), ("bird's-eye", "bird's eye"), ("bird's eye", "bird's eye"),
               ("top-down", "bird's eye"), ("worm's", "worm's eye"), ("dutch", "dutch angle"),
               ("silhouette", "silhouette"), ("two shot", "two shot"), ("tracking", "tracking"),
               ("crane", "crane"), ("reaction", "reaction"), ("medium", "medium"), ("wide", "wide"),
               ("panoram", "wide"), ("detail", "close-up")]
_ANGLE_WORDS = [("low angle", "low angle"), ("low-angle", "low angle"), ("from below", "low angle"),
                ("high angle", "high angle"), ("high-angle", "high angle"), ("from above", "high angle"),
                ("overhead", "overhead"), ("top-down", "overhead"), ("bird's", "overhead"),
                ("ground level", "ground level"), ("worm's", "ground level"), ("tilted", "tilted"),
                ("dutch", "tilted"), ("eye level", "eye level"), ("eye-level", "eye level")]
_LIGHT_WORDS = [("golden hour", "golden hour"), ("sunset", "sunset"), ("dusk", "sunset"),
                ("moonlit", "moonlight"), ("moonlight", "moonlight"), ("storm", "storm"), ("fog", "fog"),
                ("mist", "fog"), ("neon", "neon"), ("candle", "candlelight"), ("firelight", "firelight"),
                ("fireplace", "firelight"), ("noir", "low key noir"), ("low key", "low key noir"),
                ("harsh shadow", "harsh shadows"), ("deep shadow", "harsh shadows"), ("fluorescent", "industrial lighting"),
                ("industrial", "industrial lighting"), ("studio", "cinematic studio"), ("sunlit", "natural daylight"),
                ("daylight", "natural daylight"), ("morning", "natural daylight"), ("sunny", "natural daylight")]
_PALETTE_WORDS = [("sepia", "sepia"), ("black and white", "monochrome"), ("monochrome", "monochrome"),
                  ("neon", "neon"), ("pastel", "pastel"), ("gold", "gold"), ("amber", "orange"), ("orange", "orange"),
                  ("blue", "blue"), ("teal", "blue"), ("green", "green"), ("purple", "purple"), ("violet", "purple"),
                  ("red", "red"), ("crimson", "red")]
_POSE_WORDS = [(p, p) for p in POSES if p not in ("none", "holding objects")] + [
    ("holding", "holding objects"), ("hands", "holding objects"), ("point", "pointing"), ("sits", "sitting"),
    ("seated", "sitting"), ("walks", "walking"), ("runs", "running"), ("talks", "talking"), ("speaks", "talking"),
    ("watch", "observing"), ("looks at", "observing"), ("crowd", "standing")]
FRAMING_VOCAB = {w for pairs in (_SHOT_WORDS, _ANGLE_WORDS, _LIGHT_WORDS, _PALETTE_WORDS) for p, _ in pairs
                 for w in p.split()} | {"shot", "view", "angle", "light", "lighting", "lit", "framing", "frame",
                                        "camera", "palette", "tones", "colors", "colours"}
_STOP = {"a", "an", "the", "of", "on", "in", "at", "with", "and", "to", "from", "by", "is", "are", "its", "it",
         "his", "her", "their", "as", "into", "over", "under", "for", "that", "this", "while", "near"}
_WORD = re.compile(r"[a-z][a-z'-]+")


def _first(text: str, pairs: list[tuple[str, str]]) -> str:
    low = text.lower()
    hits = [(low.find(k), v) for k, v in pairs if k in low]
    return min(hits)[1] if hits else ""


def infer_location(idea: str) -> str:
    """Where the shot is, from its words: 'in/at/inside the ...' first, else what it's a shot 'of'."""
    end = r"(?=[,.;:]| with | at | as | under | while | where | of | in | on |$)"
    for pre in ("in|at|inside|on|across|outside|beside|by", "of"):
        m = re.search(rf"\b(?:{pre})\s+(?:a|an|the)\s+([a-z' -]{{3,40}}?){end}", idea.lower())
        if m:
            return " ".join(w for w in m.group(1).split() if w not in _STOP and w not in FRAMING_VOCAB)[:40]
    return ""


def infer_look(idea: str, look: dict[str, Any] | None = None) -> dict[str, Any]:
    """The shot's look, from the planner's answer where it gave one and from the idea's own words where not."""
    look = dict(look or {})
    out = {"location": (look.get("location") or "").strip().lower()[:40] or infer_location(idea),
           "shot_type": look.get("shot_type") if look.get("shot_type") in SHOT_TYPES else _first(idea, _SHOT_WORDS),
           "angle": look.get("angle") if look.get("angle") in ANGLES else _first(idea, _ANGLE_WORDS),
           "movement": look.get("movement") if look.get("movement") in MOVES else "",
           "pose": look.get("pose") if look.get("pose") in POSES else (_first(idea, _POSE_WORDS) or ""),
           "emotion": (look.get("emotion") or "").strip()[:40],
           "lighting": look.get("lighting") if look.get("lighting") in LIGHTS else _first(idea, _LIGHT_WORDS),
           "palette": look.get("palette") if look.get("palette") in PALETTES else _first(idea, _PALETTE_WORDS)}
    try:
        out["intensity"] = max(0, min(10, int(look.get("intensity"))))
    except (TypeError, ValueError):
        out["intensity"] = None
    return out


def look_schema(careful: bool = False) -> dict[str, Any]:
    """The look fields the shot planner and the director fill in (careful topics: sober choices only)."""
    pick = lambda xs: [x for x in xs if not (careful and x in CAREFUL_OUT)]  # noqa: E731
    return {"location": {"type": "string"}, "shot_type": {"type": "string", "enum": pick(SHOT_TYPES)},
            "angle": {"type": "string", "enum": pick(ANGLES)}, "movement": {"type": "string", "enum": pick(MOVES)},
            "pose": {"type": "string", "enum": POSES}, "emotion": {"type": "string"},
            "lighting": {"type": "string", "enum": pick(LIGHTS)}, "palette": {"type": "string", "enum": pick(PALETTES)},
            "intensity": {"type": "integer", "minimum": 0, "maximum": 10}}


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP and w not in FRAMING_VOCAB}


def environment_similarity(a: str, b: str) -> float:
    """How alike two shot ideas are in what they show (framing words left out), 0 to 1."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def _match(key: str, a: str, b: str) -> float:
    if key == "shot_type":
        return 1.0 if a == b else (0.6 if FAMILY.get(a) == FAMILY.get(b) else 0.0)
    if key == "location":
        wa, wb = set(a.split()) - _STOP, set(b.split()) - _STOP
        return 1.0 if a == b else (len(wa & wb) / max(1, min(len(wa), len(wb))) if wa and wb else 0.0)
    if key == "lighting":
        return 1.0 if a == b else (0.3 if TIME_OF_DAY.get(a) and TIME_OF_DAY.get(a) == TIME_OF_DAY.get(b) else 0.0)
    return 1.0 if a == b else 0.0


def similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    """0 = completely different, 100 = nearly identical. Fields neither shot has are left out of the sum."""
    total = got = 0.0
    for key, w in WEIGHTS.items():
        if key == "environment":
            total += w
            got += w * environment_similarity(a["idea"], b["idea"])
            continue
        va, vb = a["look"].get(key), b["look"].get(key)
        if not va and not vb:
            continue          # nobody knows: left out of the sum
        total += w
        got += w * _match(key, va, vb) if va and vb else 0   # known on one side only: they differ
    return round(100 * got / total) if total else 0


def history_similarity(seq: list[dict[str, Any]], i: int) -> tuple[int, str]:
    best, who = 0, ""
    for back, factor in HISTORY:
        if i - back >= 0:
            s = round(similarity(seq[i], seq[i - back]) * factor)
            if s > best:
                best, who = s, seq[i - back]["shot_id"]
    return best, who


def _streak(seq: list[dict[str, Any]], i: int, test: Callable[[dict[str, Any]], Any]) -> int:
    v = test(seq[i])
    if not v:
        return 0
    n = 0
    while i - n >= 0 and test(seq[i - n]) == v:
        n += 1
    return n


def rule_issues(seq: list[dict[str, Any]], i: int) -> list[tuple[str, str]]:
    """(rule key, plain words) for every pattern rule shot i breaks, looking back from it."""
    L = lambda k: (lambda s: s["look"].get(k))  # noqa: E731
    out = []
    if _streak(seq, i, lambda s: s["look"].get("shot_type") in CLOSE_UPS) >= 3:
        out.append(("close-ups", "3 close-ups in a row"))
    if _streak(seq, i, lambda s: s["look"].get("shot_type") == "medium") >= 4:
        out.append(("medium", "4 medium shots in a row"))
    if _streak(seq, i, L("angle")) >= 4:
        out.append(("angle", f"the same angle ({seq[i]['look']['angle']}) 4 times in a row"))
    if _streak(seq, i, lambda s: s["look"].get("movement") == "static") >= 5:
        out.append(("static", "5 static shots in a row"))
    elif seq[i]["look"].get("movement") not in ("", "static") and _streak(seq, i, L("movement")) >= 3:
        out.append(("move", f"the same camera move ({seq[i]['look']['movement']}) 3 times in a row"))
    if _streak(seq, i, L("location")) >= 4:
        out.append(("location", f"the same place ({seq[i]['look']['location']}) 4 shots running"))
    if seq[i]["look"].get("pose") not in ("", "none") and _streak(seq, i, L("pose")) >= 4:
        out.append(("pose", f"everyone {seq[i]['look']['pose']} 4 shots running"))
    if _streak(seq, i, L("lighting")) >= 5:
        out.append(("lighting", f"the same light ({seq[i]['look']['lighting']}) 5 shots running"))
    if _streak(seq, i, L("palette")) >= 5:
        out.append(("palette", f"the same colours ({seq[i]['look']['palette']}) 5 shots running"))
    last = [s["look"].get("intensity") for s in seq[max(0, i - 4):i + 1]]
    if len(last) == 5 and all(x is not None and x >= 8 for x in last):
        out.append(("pacing", "5 high-intensity shots in a row: the audience needs a breath"))
    last6 = [s["look"].get("intensity") for s in seq[max(0, i - 5):i + 1]]
    if len(last6) == 6 and None not in last6 and len(set(last6)) == 1:
        out.append(("pacing", f"6 shots at the same intensity ({last6[0]}): build and release"))
    return out


def _variety(seq: list[dict[str, Any]], i: int, *keys: str) -> int:
    window = seq[max(0, i - 9):i + 1]
    scores = []
    for k in keys:
        vals = [s["look"].get(k) for s in window if s["look"].get(k) not in ("", None, "none")]
        if vals:
            scores.append(min(1.0, len(set(vals)) / min(len(vals), 5)))
    return round(100 * sum(scores) / len(scores)) if scores else 100


def score(seq: list[dict[str, Any]], i: int) -> dict[str, Any]:
    sim, who = history_similarity(seq, i)
    issues = rule_issues(seq, i)
    pacing_bad = sum(1 for k, _ in issues if k == "pacing")
    ints = [s["look"].get("intensity") for s in seq[max(0, i - 5):i + 1] if s["look"].get("intensity") is not None]
    flat = len(ints) >= 4 and max(ints) - min(ints) <= 1
    r = {"similarity": sim, "similar_to": who if sim >= REPAIR_AT else "",
         "location": _variety(seq, i, "location"), "camera": _variety(seq, i, "shot_type", "angle", "movement"),
         "pose": _variety(seq, i, "pose"), "color": _variety(seq, i, "palette", "lighting"),
         "pacing": max(0, 100 - 30 * pacing_bad - (25 if flat else 0)),
         "issues": [t for _, t in issues], "rules": [k for k, _ in issues]}
    r["variety"] = round(0.5 * (100 - sim) + 0.5 * (r["location"] + r["camera"] + r["pose"] + r["color"]) / 4)
    return r


def verdict(r: dict[str, Any]) -> str:
    if r["similarity"] >= REJECT_AT:
        return "REJECT"
    if r["similarity"] >= REPAIR_AT or r["rules"]:
        return "REPAIR"
    return "APPROVE"


def passes(r: dict[str, Any]) -> bool:
    return r["similarity"] < REPAIR_AT and not any(k in HARD for k in r["rules"])


def _badness(r: dict[str, Any]) -> float:
    return r["similarity"] + 15 * sum(1 for k in r["rules"] if k in HARD) + 5 * len(r["rules"])


# ------------------------------------------------------------------ prompt building and continuity
def strip_framing(idea: str) -> str:
    """The idea without a framing phrase the program put in front earlier ("Low angle wide shot: ...")."""
    return re.sub(r"^[A-Z][\w' -]{0,40}(?:shot|view)[^:]{0,30}:\s*", "", idea.strip())


def look_words(look: dict[str, Any], kind: str = "broll") -> str:
    """The look in plain words for the picture prompt (the Prompt Builder): framing, light, colour, mood."""
    parts = []
    if look.get("shot_type"):
        parts.append(f"{look['shot_type']} shot" + (f", {look['angle']}" if look.get("angle") else ""))
    elif look.get("angle"):
        parts.append(look["angle"])
    if look.get("lighting"):
        parts.append(f"{look['lighting']} lighting")
    if look.get("palette"):
        parts.append(f"{look['palette']} colour palette")
    if look.get("emotion"):
        parts.append(f"mood: {look['emotion']}")
    if kind in ("caricature",) and look.get("pose") not in ("", None, "none"):
        parts.append(f"the figure is {look['pose']}")
    return ", ".join(parts)


def camera_for(look: dict[str, Any], before: str = "") -> tuple[str, str]:
    """(render camera, words for the animation model) for the director's camera move, or ("", "")."""
    move = (look or {}).get("movement") or ""
    if move not in MOVE_TO_CAMERA:
        return "", ""
    cam = MOVE_TO_CAMERA[move]
    if cam == before and cam.startswith("pan_"):   # alternate pan directions so two pans don't drift the same way
        cam = {"pan_right": "pan_left", "pan_left": "pan_right", "pan_up": "pan_down", "pan_down": "pan_up"}[cam]
    return cam, MOVE_WORDS[move]


def continuity_problem(old: dict[str, Any], new_look: dict[str, Any], new_idea: str, scene_text: str,
                       neighbours: list[dict[str, Any]]) -> str:
    """Why a rewrite breaks the story's continuity, or "" if it's fine. Continuity beats variety."""
    if new_look.get("location") and new_look["location"] != old["look"].get("location"):
        place = set(new_look["location"].split()) - _STOP
        known = _words(scene_text) | {w for n in neighbours for w in n["look"].get("location", "").split()}
        if place and not place & known:
            return f"moves to '{new_look['location']}', a place this scene never goes"
    tod = TIME_OF_DAY.get(new_look.get("lighting", ""))
    for n in neighbours:
        other = TIME_OF_DAY.get(n["look"].get("lighting", ""))
        if tod and other and tod != other:
            return f"turns {other} into {tod} in the middle of the scene"
    return ""


def rotate(seq: list[dict[str, Any]], i: int, careful: bool) -> dict[str, Any]:
    """The program's own repair: a shot type, angle and camera move not used just before."""
    cur = seq[i]
    recent = seq[max(0, i - 5):i]
    used_types = {s["look"].get("shot_type") for s in recent}
    near_fam = {FAMILY.get(s["look"].get("shot_type")) for s in seq[max(0, i - 2):i]}
    ok = lambda x: not (careful and x in CAREFUL_OUT)  # noqa: E731
    order = ["wide", "close-up", "low angle", "medium", "establishing", "over-the-shoulder", "bird's eye",
             "silhouette", "worm's eye", "extreme close-up", "two shot", "tracking", "pov", "crane", "reaction"]
    order = [t for t in order if t in SHOT_TYPES]
    shot_type = next((t for t in order if ok(t) and t not in used_types and FAMILY.get(t) not in near_fam),
                     next((t for t in order if ok(t) and FAMILY.get(t) not in near_fam), "wide"))
    angles = {s["look"].get("angle") for s in seq[max(0, i - 3):i]}
    angle = next((a for a in ["low angle", "high angle", "eye level", "overhead", "ground level", "tilted"]
                  if ok(a) and a not in angles), "eye level")
    moves = {s["look"].get("movement") for s in seq[max(0, i - 2):i]}
    statics = _streak(seq, i - 1, lambda s: s["look"].get("movement") == "static") if i else 0
    move = next((m for m in ["push-in", "pan", "pull-out", "tilt", "dolly in", "crane", "orbit", "static"]
                 if ok(m) and m not in moves and not (m == "static" and statics >= 3)), "push-in")
    look = {**cur["look"], "shot_type": shot_type, "angle": angle, "movement": move}
    idea = strip_framing(cur["idea"])
    if any(k == "pacing" for k, _ in rule_issues(seq, i)) and (cur["look"].get("intensity") or 0) >= 7:
        look["intensity"] = max(2, (cur["look"].get("intensity") or 8) - 5)
        look["movement"] = "static" if statics < 3 else "pull-out"
        idea = f"{idea.rstrip('.')}; a quiet, still moment"
    lead = f"{angle.capitalize()} {shot_type} shot" if angle != "eye level" else f"{shot_type.capitalize()} shot"
    return {"idea": f"{lead}: {idea}", "look": look}


# ------------------------------------------------------------------ the gate
REPAIR_FIELDS = {"idea": {"type": "string"}, "why": {"type": "string"}}


def _ask(llm, shot: dict[str, Any], seq: list[dict[str, Any]], i: int, r: dict[str, Any], scene: dict[str, Any],
         film: str, careful: bool, style_name: str) -> dict[str, Any]:
    recent = seq[max(0, i - 5):i]
    used = lambda k: ", ".join(dict.fromkeys(s["look"].get(k) or "?" for s in recent)) or "nothing yet"  # noqa: E731
    schema = {"type": "object", "properties": {**REPAIR_FIELDS, **look_schema(careful)},
              "required": ["idea", "why", "location", "shot_type", "angle", "movement", "pose", "emotion",
                           "lighting", "palette", "intensity"]}
    system = (
        "You are the Virtual Director: film director, cinematographer, storyboard supervisor and visual quality "
        f"controller for a {style_name} video. You are NOT the writer: the story decides WHAT this shot shows "
        "and why; you decide HOW it is shown. Ask: what is the most visually interesting way to show this "
        "moment? Rewrite the shot so it no longer repeats the shots before it. Keep the story meaning, the "
        "subject and the story function. Change the camera, composition, angle, lighting, camera move, pose "
        "and mood. Story continuity overrides variety: stay in the scene's place (a different corner, view or "
        "detail of it is fine; a cutaway to an object the narration names is fine), keep the time of day and "
        "the weather. Never name a real person, never ask for readable text, signs or logos, and never add "
        "people the shot didn't have. The idea is one or two sentences for an illustrator."
        + (f"\n{film}\nKeep to that directing style." if film else "")
        + ("\nCareful topic: sober, respectful framing only." if careful else "")
        + ("\nThis is Owlbert's empty set: describe only the place, never the owl." if shot["kind"] == "owl" else ""))
    user = (f"Scene narration: {scene.get('narration', '')[:900]}\nScene visual note: {scene.get('visual', '')}\n"
            f"Recent shots (oldest first):\n" + "\n".join(
                f"- {s['shot_id']}: {s['look'].get('shot_type') or '?'}, {s['look'].get('angle') or '?'}, "
                f"{s['look'].get('movement') or '?'}, {s['look'].get('lighting') or '?'}, "
                f"{s['look'].get('palette') or '?'} | {s['idea'][:110]}" for s in recent)
            + f"\n\nThe shot to repair ({shot['shot_id']}, {shot['kind']}): {shot['idea']}\n"
            f"Its look: {shot['look']}\nWhat's wrong: similarity {r['similarity']}% to {r['similar_to'] or 'the shots before'}"
            + (f"; {'; '.join(r['issues'])}" if r["issues"] else "")
            + f"\nUsed recently, so pick something else: shot types {used('shot_type')}; angles {used('angle')}; "
              f"moves {used('movement')}; light {used('lighting')}; colours {used('palette')}.\n"
              "intensity: 0 = calm reflection, 4 = talk, 5 = investigation, 8 = action, 10 = the biggest moment.")
    return llm.chat_json([{"role": "system", "content": system}, {"role": "user", "content": user}], schema,
                         lenient=True, temperature=0.8)


def direct(scenes: list[dict[str, Any]], *, film: str = "", careful: bool = False, style_name: str = "",
           names: list[str] | None = None, on_progress: Callable[[str, float], None] | None = None,
           log: Callable[[str], None] | None = None, repair: bool = True) -> dict[str, Any]:
    """Review (and repair) every shot of the planned storyboard, in order. repair=False only scores (used when
    you remake one shot, so your change doesn't set off repaints of the shots around it). Changes the shots in place and
    returns the review. A changed shot gets 'directed_from' (its old idea) so the caller repaints it."""
    from .llm import Ollama
    from .stages.storyboard import names_in
    cfg = settings().get("director", {})
    ai_left = int(cfg.get("ai_repairs", 30))
    tries = max(0, int(cfg.get("tries", 2)))
    names = names or []
    llm = Ollama(job="director")
    seq: list[dict[str, Any]] = []
    scene_of: dict[str, dict[str, Any]] = {}
    for sc in scenes:
        for sh in sc.get("shots", []):
            sh["look"] = infer_look(sh["idea"], sh.get("look"))
            seq.append(sh)
            scene_of[sh["shot_id"]] = sc
    rows = []
    total = len(seq)
    for i, sh in enumerate(seq):
        sc = scene_of[sh["shot_id"]]
        r = score(seq, i)
        first = verdict(r)
        before = {"idea": sh["idea"], "look": dict(sh["look"])}
        changes: list[str] = []
        if first != "APPROVE" and repair and not sh.get("by_hand"):
            if on_progress:
                on_progress(f"Virtual Director: repairing {sh['shot_id']} ({first.lower()}, {r['similarity']}% "
                            f"like {r['similar_to'] or 'the shots before'})", 100 * i / max(1, total))
            best = (sh["idea"], dict(sh["look"]), r)
            neighbours = [s for s in seq[max(0, i - 3):i] if scene_of[s["shot_id"]] is sc]
            scene_text = f"{sc.get('narration', '')} {sc.get('visual', '')} {before['idea']}"
            for _ in range(tries if ai_left > 0 else 0):
                ai_left -= 1
                try:
                    ans = _ask(llm, sh, seq, i, r, sc, film, careful, style_name)
                except StageError as exc:
                    changes.append(f"the director AI couldn't answer ({exc})")
                    break
                idea = (ans.get("idea") or "").strip()
                look = infer_look(idea, ans)
                if not idea or names_in(idea, names):
                    changes.append("an AI rewrite named a real person or came back empty: turned down")
                    continue
                broke = continuity_problem(sh, look, idea, scene_text, neighbours)
                if broke:
                    changes.append(f"an AI rewrite {broke}: turned down (continuity first)")
                    continue
                sh["idea"], sh["look"] = idea, look
                r2 = score(seq, i)
                if _badness(r2) < _badness(best[2]):
                    best = (idea, dict(look), r2)
                    changes.append(f"rewritten by the director AI: {(ans.get('why') or '').strip()[:160]}")
                if passes(r2):
                    break
            sh["idea"], sh["look"], r = best[0], dict(best[1]), best[2]
            if not passes(r):
                fix = rotate(seq, i, careful)
                sh["idea"], sh["look"] = fix["idea"], fix["look"]
                r3 = score(seq, i)
                if _badness(r3) < _badness(r):
                    r = r3
                    changes.append(f"reframed by the program: {fix['look']['shot_type']}, {fix['look']['angle']}, "
                                   f"{fix['look']['movement']}")
                else:
                    sh["idea"], sh["look"] = best[0], dict(best[1])
        changed = sh["idea"] != before["idea"] or sh["look"] != before["look"]
        if changed:
            sh["directed_from"] = before["idea"]
        if first == "APPROVE" and not changed:
            decision = "APPROVED"
        elif r["similarity"] >= REJECT_AT or any(k in HARD for k in r["rules"]):
            decision = "REJECTED"
        elif changed:
            decision = "REPAIRED"
        else:
            decision = "APPROVED"   # only soft notes left (continuity kept the place or the light)
        review = {**{k: v for k, v in r.items() if k != "rules"}, "decision": decision, "first_look": first,
                  "changes": [c for c in changes if c], **({"by_hand": True} if sh.get("by_hand") else {})}
        if changed:
            review["before"] = before
        sh["review"] = review
        rows.append({"shot_id": sh["shot_id"], "scene_id": sc["scene_id"], "idea": sh["idea"], "look": sh["look"],
                     **review})
        if log and decision != "APPROVED":
            log(f"Virtual Director: {sh['shot_id']} {decision}" + (f" ({'; '.join(r['issues'])})" if r["issues"] else "")
                + (f", {r['similarity']}% like {r['similar_to']}" if r["similar_to"] else ""))
    counts = {d: sum(1 for x in rows if x["decision"] == d) for d in ("APPROVED", "REPAIRED", "REJECTED")}
    avg = lambda k: round(sum(x[k] for x in rows) / len(rows)) if rows else 0  # noqa: E731
    summary = {"shots": len(rows), **counts, "variety": avg("variety"), "location": avg("location"),
               "camera": avg("camera"), "pose": avg("pose"), "color": avg("color"), "pacing": avg("pacing"),
               "similarity": avg("similarity")}
    return {"summary": summary, "shots": rows}


def to_markdown(review: dict[str, Any]) -> str:
    s = review["summary"]
    out = ["# Virtual Director review", "",
           f"{s['shots']} shots: {s['APPROVED']} approved, {s['REPAIRED']} repaired, {s['REJECTED']} rejected. "
           f"Variety {s['variety']}/100, camera {s['camera']}, locations {s['location']}, poses {s['pose']}, "
           f"colour {s['color']}, pacing {s['pacing']}.", ""]
    for x in review["shots"]:
        out += [f"## {x['shot_id']}", "DIRECTOR REVIEW", "",
                f"Similarity Score: {x['similarity']}%" + (f" (to {x['similar_to']})" if x["similar_to"] else ""),
                f"Variety Score: {x['variety']}/100", f"Location Diversity: {x['location']}/100",
                f"Camera Diversity: {x['camera']}/100", f"Pose Diversity: {x['pose']}/100",
                f"Color Diversity: {x['color']}/100", f"Pacing Score: {x['pacing']}/100", "",
                f"Decision: **{x['decision']}**" + (" (your own idea: scored, not rewritten)" if x.get("by_hand") else "")]
        if x["issues"]:
            out.append("Notes: " + "; ".join(x["issues"]))
        if x.get("changes"):
            out.append("What changed: " + "; ".join(x["changes"]))
        if x["decision"] == "REPAIRED":
            lk = x["look"]
            out += ["", f"Revised shot: {x['idea']}",
                    f"Look: {lk.get('shot_type') or '-'}, {lk.get('angle') or '-'}, move {lk.get('movement') or '-'}, "
                    f"{lk.get('location') or '-'}, {lk.get('pose') or '-'}, {lk.get('lighting') or '-'}, "
                    f"{lk.get('palette') or '-'}, intensity {lk.get('intensity') if lk.get('intensity') is not None else '-'}",
                    f"Was: {x['before']['idea']}"]
        out.append("")
    return "\n".join(out)


def tooltip(review: dict[str, Any] | None) -> str:
    if not review:
        return "Not reviewed by the Virtual Director yet (press Make pictures)."
    lines = [f"Virtual Director: {review['decision']}", f"Similarity {review['similarity']}%"
             + (f" to {review['similar_to']}" if review.get("similar_to") else ""),
             f"Variety {review['variety']} · camera {review['camera']} · locations {review['location']} · poses "
             f"{review['pose']} · colour {review['color']} · pacing {review['pacing']}"]
    lines += [f"- {t}" for t in review.get("issues", [])]
    lines += [f"• {t}" for t in review.get("changes", [])]
    if review.get("before"):
        lines.append(f"Was: {review['before']['idea'][:200]}")
    return "\n".join(lines)
