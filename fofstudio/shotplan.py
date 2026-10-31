"""Shots that follow the script (Dave, 2026-10-31: "they don't seem to follow the script, repeat image types way
too much and when they are animated they break").

Three causes were found in the old planner, and this module fixes them:
  1. the local AI got the whole scene's narration and was asked for N shots, so it never knew which words each
     picture was for, and drifted to generic pictures. Now the narration is cut into N pieces (whole sentences,
     long ones at commas) and every shot is planned for its own words ("covers"): show what is being said;
  2. pictures were spread evenly over the scene, whatever was being said. Now each shot comes on screen when
     Owlbert starts saying its words (production lines the cuts up with the word timings);
  3. the variety check compared the framing (wide, close, angle...) but not WHAT a picture shows, so "a desk with
     documents" came back again and again in different framings. Now every shot says what kind of thing it
     shows (SHOWS), the planner sees the last shots of the whole film, and the same kind of subject can't come
     twice in a row or fill a scene.
And for animation: a picture is only given to the image-to-video model when it's safe to animate (one clear
subject, no writing, no small faces or hands, no crowds); the rest move in 2.5D, which can't melt or morph.
Motion prompts say only what moves and how the camera moves, one action, never "no ...".
"""

from __future__ import annotations

import re
from typing import Any

# what a picture shows (the subject, not the framing)
SHOWS = ["place", "building", "object", "document", "map or diagram", "money or goods", "crowd from behind",
         "single figure from behind", "hands at work", "machine or technology", "nature or weather", "symbol or metaphor",
         "broadcast or media", "timeline or calendar", "owl set", "caricature"]
MAX_SAME_SHOWS_PER_SCENE = 2      # e.g. at most two document pictures in one scene
PAPERWORK = {"document", "map or diagram", "timeline or calendar"}

_SENT = re.compile(r"(?<=[.!?])[\"”’)]*\s+")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split((text or "").strip()) if s.strip()]


def segments(narration: str, n: int) -> list[str]:
    """Cut the narration into n pieces of about the same length, at sentence ends where possible, at commas or
    between words when a sentence has to be shared. Every word is in exactly one piece, in order."""
    n = max(1, n)
    words = (narration or "").split()
    if not words:
        return [""] * n
    if n == 1:
        return [" ".join(words)]
    # candidate cut points: after a sentence end (best), after a comma or dash (ok), anywhere (last resort)
    target = len(words) / n
    cuts: list[int] = []
    for k in range(1, n):
        ideal = round(k * target)
        best, best_cost = None, 1e9
        for j in range(max(1, ideal - int(target * 0.6) - 1), min(len(words), ideal + int(target * 0.6) + 2)):
            if cuts and j <= cuts[-1]:
                continue
            w = words[j - 1]
            bonus = 0 if re.search(r"[.!?][\"”’)]*$", w) else 2 if re.search(r"[,;:—–-]$", w) else 4
            cost = abs(j - ideal) / max(1.0, target) * 3 + bonus
            if cost < best_cost:
                best, best_cost = j, cost
        if best is None:
            best = min(len(words) - (n - k), max((cuts[-1] + 1) if cuts else 1, ideal))
        cuts.append(best)
    bounds = [0] + cuts + [len(words)]
    out = [" ".join(words[a:b]) for a, b in zip(bounds, bounds[1:])]
    while len(out) < n:          # more shots than words: the last words are shown twice, never nothing
        out.append(out[-1])
    return out[:n]


def recent_for_prompt(planned: list[dict[str, Any]], so_far: list[dict[str, Any]], k: int = 8) -> list[str]:
    """The last k shots of the film so far (earlier scenes and this one), for "don't repeat these"."""
    seq = [s for e in planned for s in e.get("shots", [])] + list(so_far)
    return [f"[{s.get('shows') or s.get('kind')}] {s['idea'][:80]}" for s in seq[-k:]]


def shows_problems(seq: list[dict[str, Any]]) -> list[tuple[int, str]]:
    """Shots whose subject repeats the one before, or overfills the scene (by index in seq)."""
    out = []
    per_scene: dict[tuple[str, str], int] = {}
    for i, s in enumerate(seq):
        what = s.get("shows") or ""
        if not what or what in ("owl set", "caricature"):
            continue
        key = (s.get("scene_id") or s.get("shot_id", "")[:9], what)
        per_scene[key] = per_scene.get(key, 0) + 1
        if i and (seq[i - 1].get("shows") == what or
                  (what in PAPERWORK and seq[i - 1].get("shows") in PAPERWORK)):
            out.append((i, f"shows {what} again, straight after another {seq[i - 1].get('shows')}"))
        elif per_scene[key] > MAX_SAME_SHOWS_PER_SCENE:
            out.append((i, f"the {per_scene[key]}th '{what}' picture in this scene"))
    return out


def alternative_shows(seq: list[dict[str, Any]], i: int, scene_shows: list[str]) -> list[str]:
    """Subject kinds this shot could switch to: not used just before or after, rare in the scene."""
    near = {seq[j].get("shows") for j in (i - 2, i - 1, i + 1) if 0 <= j < len(seq)}
    used = {w: scene_shows.count(w) for w in set(scene_shows)}
    opts = [w for w in SHOWS if w not in near and w not in ("owl set", "caricature")
            and not (w in PAPERWORK and near & PAPERWORK)]
    return sorted(opts, key=lambda w: used.get(w, 0))


# ---------------------------------------------------------------- animation safety
RISKY = re.compile(r"\b(?:hands?|fingers?|faces?|crowds?|people|audience|text|writing|letters?|headlines?|signs?|"
                   r"screens?|monitors?|keyboards?|typing|newspapers?|pages?|documents?|papers?|books?|maps?|charts?|"
                   r"diagrams?|calendars?|clocks?|grids?|patterns?|reflections?|mirrors?|wheels?|spokes?|fences?|"
                   r"railings?|stairs|teeth|eyes)\b", re.I)
SAFE_SHOWS = {"place", "building", "nature or weather", "machine or technology", "symbol or metaphor",
              "single figure from behind", "money or goods", "object", "owl set"}


COMPOSE = "one clear main subject with a clean silhouette, set apart from a simple uncluttered background"
SHOWS_RISK = {"place": 10, "building": 10, "nature or weather": 5, "machine or technology": 15, "symbol or metaphor": 15,
              "object": 15, "money or goods": 25, "single figure from behind": 25, "owl set": 10, "broadcast or media": 45,
              "crowd from behind": 60, "hands at work": 70, "document": 70, "map or diagram": 70,
              "timeline or calendar": 70, "caricature": 55}
LOW, HIGH = 35, 65


def animation_risk(shot: dict[str, Any]) -> dict[str, Any]:
    """Animation Validation (Dave's brief, 2026-10-31): how likely this picture is to break when the image-to-video
    model moves it, 1-100, with the reasons. Low (under 35): safe to animate. Medium: drawn with a cleaner
    composition and given gentle motion. High (65 and up): never sent to the animation model; it moves in 2.5D
    (a camera move with depth), which can't melt, morph or flicker. From the research: one clear subject with a
    clean silhouette and a simple background animates well; writing, faces, hands, crowds, fine patterns and
    heavy overlap break."""
    why: list[str] = []
    if shot.get("real") or (shot.get("image") or {}).get("real"):
        return {"risk": 100, "band": "high", "why": ["a real photo is never changed by AI"]}
    what = shot.get("shows") or ("caricature" if shot.get("kind") == "caricature" else "")
    score = SHOWS_RISK.get(what, 30)
    if what:
        why.append(f"{what}: {score}")
    idea = f"{shot.get('idea', '')} {shot.get('prompt', '')}"
    hits = sorted({m.group(0).lower() for m in RISKY.finditer(idea)})
    if hits:
        score += min(40, 12 * len(hits))
        why.append("melts or flickers when animated: " + ", ".join(hits[:4]))
    shot_type = (shot.get("look") or {}).get("shot_type", "")
    if shot_type == "extreme close-up":
        score += 15
        why.append("an extreme close-up has nothing to move but the surface")
    if shot_type in ("establishing", "wide", "bird's eye") and what in ("crowd from behind",):
        score += 10
        why.append("a wide crowd means many tiny figures")
    if (shot.get("look") or {}).get("angle") == "tilted":
        score += 5
        why.append("a tilted frame warps when the camera moves")
    act = (shot.get("action") or "").lower()
    if re.search(r"\b(?:run|runs|running|fight|fights|dance|dances|juggl\w*|spins?|tumbl\w*|crowd\w*)\b", act):
        score += 15
        why.append(f"a fast or complex action ({act[:40]})")
    score = max(1, min(100, score))
    band = "low" if score < LOW else "high" if score >= HIGH else "medium"
    return {"risk": score, "band": band, "why": why or ["one clear subject: safe to animate"]}


def motion_safety(shot: dict[str, Any]) -> tuple[str, str]:
    """('ai', why) when the image-to-video model may move this picture, ('2.5d', why) when it gets a camera move
    with depth instead."""
    r = shot.get("anim") or animation_risk(shot)
    return ("ai" if r["band"] != "high" else "2.5d"), "; ".join(r["why"])


NEGATION = re.compile(r"(?:,\s*|\.\s*|\b)(?:with\s+)?(?:no|never|not|don't|do not|without)\s+[^,.;]*", re.I)


def clean_motion(text: str, camera_words: str = "") -> str:
    """A motion prompt for image-to-video: what moves and how the camera moves, one action, no 'no ...'
    (with the fast settings the model can't use negatives, and the words pull the thing in)."""
    t = NEGATION.sub("", text or "")
    t = re.sub(r"\s{2,}", " ", t).strip(" ,.")
    first = sentences(t)[:2]          # one action: at most two short sentences
    out = ". ".join(s.strip(" .") for s in first if s.strip(" ."))
    if camera_words and camera_words.lower() not in out.lower():
        out = f"{out}. {camera_words}" if out else camera_words
    return (out or "gentle natural movement").strip(" .") + "."


# ---------------------------------------------------------------- scene diversity scores
TRACKED = ("shows", "shot_type", "angle", "movement", "location", "pose", "lighting", "palette", "emotion")


def _field(shot: dict[str, Any], key: str) -> str:
    if key in ("shows", "emotion"):
        return shot.get(key) or ""
    return ((shot.get("look") or {}).get(key) or "") if key != "shot_type" else \
        ((shot.get("look") or {}).get("shot_type") or "")


def diversity(seq: list[dict[str, Any]]) -> int:
    """0-100: how evenly the shots spread over subjects, framings, angles, moves, places, poses, light, colour
    and emotion (normalised entropy, averaged). 100 = never the same twice; low = the same picture again."""
    import math
    if len(seq) < 2:
        return 100
    scores = []
    for key in TRACKED:
        vals = [v for v in (_field(s, key) for s in seq) if v]
        if len(vals) < 2:
            continue
        counts: dict[str, int] = {}
        for v in vals:
            counts[v] = counts.get(v, 0) + 1
        h = -sum(c / len(vals) * math.log(c / len(vals)) for c in counts.values())
        scores.append(h / math.log(min(len(vals), 8)) if min(len(vals), 8) > 1 else 1.0)
    return int(round(100 * min(1.0, sum(scores) / len(scores)))) if scores else 100


def diversity_windows(seq: list[dict[str, Any]]) -> dict[str, int]:
    """The Scene Diversity scores the brief asks for: the last 20 shots, the last 50 and the whole video."""
    return {"last_20": diversity(seq[-20:]), "last_50": diversity(seq[-50:]), "all": diversity(seq)}


def emotion_streaks(seq: list[dict[str, Any]], limit: int = 4) -> list[int]:
    """Shots that make a run of more than `limit` shots in the same emotional tone."""
    out, run = [], 1
    for i in range(1, len(seq)):
        same = seq[i].get("emotion") and seq[i].get("emotion") == seq[i - 1].get("emotion")
        run = run + 1 if same else 1
        if run > limit:
            out.append(i)
    return out


# ---------------------------------------------------------------- the Motion Planner's three layers
ENVIRONMENT = ["none", "drifting smoke", "moving clouds", "falling rain", "falling snow", "flickering firelight",
               "passing traffic", "rustling leaves", "rippling water", "floating dust", "flickering light",
               "rising steam", "wind in the grass", "a distant crowd shifting"]
SPEEDS = ["very slow", "slow", "steady"]


def motion_prompt(camera_words: str, speed: str, character: str, environment: list[str], band: str) -> str:
    """The image-to-video prompt from the three layers (Wan's own advice for image-to-video: describe only the
    motion and the camera; the picture already shows the rest). Medium-risk pictures get no character action,
    only the surroundings and the camera, so nothing that could melt is asked to move."""
    env = [e for e in environment if e and e != "none"][:2]
    parts = []
    if character and band == "low":
        parts.append(character)
    if env:
        parts.append(" and ".join(env))
    else:   # research: say what stays still, so the model doesn't invent motion everywhere
        parts.append("the background stays steady")
    cam = camera_words or "the camera holds still"
    parts.append(f"{cam}, {speed}" if speed and speed not in cam else cam)
    tidy = [re.sub(r"\s{2,}", " ", NEGATION.sub("", p)).strip(" ,.") for p in parts]   # each layer, one sentence
    return ". ".join(t for t in tidy if t) + "."
