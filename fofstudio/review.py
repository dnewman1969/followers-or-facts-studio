"""Quality Review Agent (Dave's brief, 2026-10-31): the final review, like a human director looking at the
storyboard before it goes to animation.

It answers the brief's nine questions, each with its evidence and the shots or scenes it's about:
  1 Did the storyboard follow the script?      every shot covers its own narration words, and the local vision
                                               model agrees the painted picture shows what was planned
  2 Did all major story moments appear?        every scene has pictures, and what the film's bible says must be
                                               seen in a scene appears in one of its shots
  3 Are characters consistent?                 caricatures only from approved designs; anonymous people drawn
                                               from the bible's fixed descriptions; Owlbert is his artwork
  4 Are locations consistent?                  a scene stays in its bible location (at most two places a scene)
  5 Are scenes visually diverse?               the diversity score over the last 20, 50 and all shots, and no
                                               subject repeated back to back
  6 Will scenes animate successfully?          only low/medium-risk pictures go to the animation model
  7 Does pacing feel cinematic?                shots average 2.5-8 seconds and none sits longer than 12
  8 Do camera movements make sense?            not mostly static, no ping-pong pans, no three identical moves
  9 Would a human director approve this?       yes only if every answer above is yes
The numbers are counted by the program (the same answer every time); the vision model is only asked plain
yes/no questions about single pictures, and only as a check (research: small vision models miss text and
counting, so a 'no' leads to one repaint, never to deleting anything). If any answer is NO, the storyboard
stage repaints the failing shots and re-plans the failing scenes once, automatically (storyboard.py).
"""

from __future__ import annotations

import base64
import io
import re
from typing import Any

from . import shotplan

QUESTIONS = [
    ("script", "Did the storyboard follow the script?"),
    ("moments", "Did all major story moments appear?"),
    ("characters", "Are characters consistent?"),
    ("locations", "Are locations consistent?"),
    ("diverse", "Are scenes visually diverse?"),
    ("animate", "Will scenes animate successfully?"),
    ("pacing", "Does pacing feel cinematic?"),
    ("camera", "Do camera movements make sense?"),
    ("director", "Would a human director approve this sequence?"),
]
_WORD = re.compile(r"[a-z]{4,}")
STOP = {"with", "that", "this", "from", "into", "their", "there", "where", "which", "shown", "shows", "seen",
        "under", "over", "while", "about", "light", "scene", "picture", "clear"}


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in STOP}


# ---------------------------------------------------------------- one painted picture
def frame_check(image_path, shot: dict[str, Any], drawn: bool = True, llm=None) -> dict[str, Any] | None:
    """Ask the local vision model three yes/no questions about one painted picture. None when no vision model
    answers (the review then says the pictures weren't looked at, and nothing is repainted for it)."""
    from PIL import Image

    from . import cast
    from .util import StageError
    try:
        img = Image.open(image_path).convert("RGB")
        img.thumbnail((768, 768))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88)
        b64 = base64.b64encode(buf.getvalue()).decode()
    except OSError:
        return None
    subject = shot.get("shows") or shot.get("kind", "")
    idea = (shot.get("idea") or "")[:160]
    qs = [f"Does the picture mainly show {subject}: {idea}?",
          "Is there any readable writing, lettering or numbers in the picture?",
          "Is there one clear main subject that stands out from the background?"]
    if drawn:
        qs.append("Is it a drawing, painting or illustration (not a photograph)?")
    prompt = ("Answer each question with only yes or no, one per line, like '1. yes'.\n"
              + "\n".join(f"{n}. {q}" for n, q in enumerate(qs, 1)))
    try:
        if llm is None:
            from .config import settings
            from .llm import Ollama
            llm = Ollama({**settings()["ollama"], "num_ctx": 4096, "num_predict": 120, "max_predict": 240,
                          "max_ctx": 4096}, job="vision")
        text = llm.chat([{"role": "user", "content": prompt, "images": [b64]}], model=cast.vision_model(),
                        temperature=0)
    except (StageError, Exception):  # noqa: BLE001 - no vision model running: the review says so
        return None
    answers: dict[int, bool] = {}
    for line in (text or "").lower().splitlines():
        m = re.match(r"\s*(\d)[.):\s-]+\s*(yes|no)\b", line)
        if m:
            answers[int(m.group(1))] = m.group(2) == "yes"
    if len(answers) < len(qs):
        words = re.findall(r"\b(yes|no)\b", (text or "").lower())
        answers = {n: w == "yes" for n, w in enumerate(words[:len(qs)], 1)} if len(words) >= len(qs) else answers
    if len(answers) < len(qs):
        return None
    problems = []
    if not answers[1]:
        problems.append("doesn't show what was planned")
    if answers[2]:
        problems.append("has writing in it")
    if not answers[3]:
        problems.append("no clear main subject (it may break when animated)")
    if drawn and not answers.get(4, True):
        problems.append("looks like a photograph, not the drawn style")
    return {"ok": not problems, "problems": problems, "answers": answers}


# ---------------------------------------------------------------- the whole storyboard
def sequence_review(board: dict[str, Any], bible: dict[str, Any], frame_results: dict[str, dict] | None = None,
                    clip_results: dict[str, dict] | None = None) -> dict[str, Any]:
    """The nine questions, answered from the planned and painted storyboard."""
    frame_results = frame_results or {}
    scenes = board.get("scenes", [])
    seq = [{**sh, "scene_id": sc["scene_id"]} for sc in scenes for sh in sc.get("shots", []) if not sh.get("skip")]
    out: dict[str, dict[str, Any]] = {}

    # 1 follow the script
    uncovered = [sh["shot_id"] for sh in seq if not sh.get("covers") and not sh.get("by_hand")]
    off = [sid for sid, r in frame_results.items() if r and "doesn't show what was planned" in r["problems"]]
    looked = sum(1 for r in frame_results.values() if r)
    out["script"] = {"ok": not uncovered and not off, "shots": sorted(set(uncovered + off)),
                     "why": ("every shot covers its own narration words"
                             + (f", and the vision model agreed for {looked - len(off)} of {looked} pictures"
                                if looked else " (the pictures weren't looked at: no vision model answered)"))
                     if not uncovered and not off else
                     (f"{len(uncovered)} shot(s) aren't tied to narration words; " if uncovered else "")
                     + (f"{len(off)} picture(s) don't show what was planned" if off else "")}

    # 2 major story moments
    missing, empty = [], []
    for sc in scenes:
        shots = [sh for sh in sc.get("shots", []) if not sh.get("skip")]
        if not shots and sc.get("narration"):
            empty.append(sc["scene_id"])
            continue
        text = " ".join(f"{sh.get('idea', '')} {sh.get('covers', '')}" for sh in shots)
        have = _words(text)
        for item in ((bible.get("scenes") or {}).get(sc["scene_id"]) or {}).get("must_show", []):
            if _words(item) and not (_words(item) & have):
                missing.append((sc["scene_id"], item))
    out["moments"] = {"ok": not missing and not empty, "scenes": sorted({s for s, _ in missing} | set(empty)),
                      "why": "every scene has its pictures and everything the bible says must be seen"
                      if not missing and not empty else
                      "; ".join([f"{s} has no pictures" for s in empty] +
                                [f"{s}: nothing shows '{item}'" for s, item in missing[:6]])}

    # 3 characters
    stray = [sh["shot_id"] for sh in seq if sh.get("kind") == "caricature" and not sh.get("person_id")]
    out["characters"] = {"ok": not stray, "shots": stray,
                         "why": "caricatures come only from approved designs, anonymous people from the bible's fixed "
                                "descriptions, and Owlbert from his artwork" if not stray else
                                f"{len(stray)} caricature shot(s) without an approved person"}

    # 4 locations
    wander = []
    for sc in scenes:
        places = {(sh.get("look") or {}).get("location", "") for sh in sc.get("shots", []) if sh.get("kind") == "broll"}
        places.discard("")
        bible_loc = ((bible.get("scenes") or {}).get(sc["scene_id"]) or {}).get("location")
        if len(places) > 3 and bible_loc:
            wander.append(sc["scene_id"])
    out["locations"] = {"ok": not wander, "scenes": wander,
                        "why": "each scene keeps to its place (the bible's location is drawn the same every time)"
                        if not wander else f"{len(wander)} scene(s) jump between more than three places"}

    # 5 diversity
    win = shotplan.diversity_windows(seq)
    reps = shotplan.shows_problems(seq)
    out["diverse"] = {"ok": min(win.values()) >= 55 and len(reps) <= max(1, len(seq) // 15),
                      "shots": [seq[i]["shot_id"] for i, _ in reps], "scores": win,
                      "why": f"variety {win['last_20']} (last 20 shots), {win['last_50']} (last 50), {win['all']} "
                             f"(whole video); {len(reps)} subject repeat(s)"}

    # 6 animation
    risky = [sh["shot_id"] for sh in seq if (sh.get("anim") or {}).get("band") == "high"]
    broken = [sid for sid, r in (clip_results or {}).items() if r and not r.get("ok")]
    unclear = [sid for sid, r in frame_results.items() if r and any("no clear main subject" in p for p in r["problems"])]
    out["animate"] = {"ok": not broken and not unclear, "shots": broken + unclear,
                      "why": f"{len(seq) - len(risky)} of {len(seq)} pictures are safe for the animation model; the "
                             f"{len(risky)} risky ones (writing, crowds, hands, documents) move in 2.5D, which can't "
                             "break" + (f"; {len(broken)} clip(s) broke" if broken else "")
                             + (f"; {len(unclear)} picture(s) have no clear subject" if unclear else "")}

    # 7 pacing (research: narrated stills with camera moves hold about 5-20 s, around 12 s in long-form
    # documentaries; feature-film averages under 4 s are the wrong target; judge the median and the spread,
    # and a shot rhythm that never changes reads as metronomic)
    lens = []
    for sc in scenes:
        shots_ = [sh for sh in sc.get("shots", []) if not sh.get("skip")]
        if shots_:
            lens += [float(sc.get("seconds") or 0) / len(shots_)] * len(shots_)
    lens.sort()
    med = lens[len(lens) // 2] if lens else 0.0
    mean = sum(lens) / len(lens) if lens else 0.0
    cv = ((sum((x - mean) ** 2 for x in lens) / len(lens)) ** 0.5 / mean) if lens and mean else 1.0
    slow = [sc["scene_id"] for sc in scenes if sc.get("shots")
            and float(sc.get("seconds") or 0) / max(1, len([x for x in sc["shots"] if not x.get("skip")])) > 15]
    rushed = med and med < 2.5
    out["pacing"] = {"ok": bool(not lens or (2.5 <= med <= 12 and not slow)), "scenes": slow,
                     "median": round(med, 1), "variation": round(cv, 2),
                     "why": f"shots hold {med:.1f} seconds (median)"
                            + ("; too fast to take in" if rushed else "")
                            + (f"; {len(slow)} scene(s) hold one picture over 15 seconds" if slow else "")
                            + ("; every shot is the same length (metronomic)" if lens and cv < 0.08 and len(lens) > 8
                               else "")}

    # 8 camera
    moves = [(sh.get("look") or {}).get("movement") or "" for sh in seq]
    static = sum(1 for m in moves if m in ("", "static"))
    pingpong = [seq[i]["shot_id"] for i in range(2, len(moves)) if moves[i] and moves[i] == moves[i - 1] == moves[i - 2]
                and moves[i] != "static"]
    out["camera"] = {"ok": static <= 0.5 * max(1, len(moves)) and not pingpong, "shots": pingpong,
                     "why": f"{len(moves) - static} of {len(moves)} shots move" +
                            (f"; the same move three times running at {', '.join(pingpong[:3])}" if pingpong else "")}

    all_ok = all(v["ok"] for v in out.values())
    out["director"] = {"ok": all_ok, "why": "every check passed" if all_ok else
                       "not yet: " + ", ".join(q for k, q in QUESTIONS if k in out and not out[k]["ok"])}
    return {"answers": out, "approved": all_ok,
            "redo_shots": sorted({s for k in ("script", "animate") for s in out[k].get("shots", [])}),
            "redo_scenes": sorted({s for k in ("moments", "locations", "pacing") for s in out[k].get("scenes", [])})}


def to_markdown(review: dict[str, Any]) -> str:
    lines = ["# Quality review", ""]
    for key, q in QUESTIONS:
        a = review["answers"].get(key)
        if a:
            lines.append(f"- **{q}** {'YES' if a['ok'] else 'NO'}: {a['why']}")
    if review.get("redone"):
        lines += ["", f"Redone automatically: {review['redone']}"]
    return "\n".join(lines) + "\n"
