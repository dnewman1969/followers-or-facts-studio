"""Production: the editing timeline.

Tracks (top to bottom, like a video editor):
  V1 Video    intro bumper, every approved clip in scene order, outro bumper
  V2 Owlbert  when the talking owl presenter shows in the corner
  V3 Moves    Owlbert's moves: flying in and off, pointing at the evidence, the hat trick
  A3 Effects  whooshes, pops and stings that go with the moves and the music
  A1 Speech   Owlbert reading each scene of the script
  A2 Music    the music bed (ducked under his voice when rendered)

"Assemble" lines everything up automatically: each scene's clips are stretched to fill the
time Owlbert takes to read that scene. You can then drag, trim and nudge anything in the
editor; the timeline is saved to production.json and the Render stage follows it exactly.
"""

from __future__ import annotations

import re

from typing import Any

from .. import bits, media, owl
from ..config import settings
from ..episode import Episode
from ..util import StageError, read_json, utc_now, write_json
from .base import BLOCK, OK, WARN, Check, Context
from .script import load as load_script
from .video import load_plan

LEAD = 0.35          # Owlbert starts talking this long after his scene appears
TAIL = 0.6           # breathing room after each scene
FADE = 0.4           # cross-fade between clips inside a scene
SCENE_FADE = 0.6     # cross-fade between scenes


def path(ep: Episode):
    return ep.path("production.json")


MIX_KEYS = ("speech_db", "music_db", "master_db")


def mix(tl: dict[str, Any]) -> dict[str, float]:
    """This video's sound mix in dB: its own if you moved the sliders, else the defaults from Settings."""
    snd = settings()["sound"]
    own = tl.get("mix") or {}
    return {k: float(own.get(k, snd[k])) for k in MIX_KEYS}


def load(ep: Episode) -> dict[str, Any]:
    return read_json(path(ep), {}) or {}


def save(ep: Episode, tl: dict[str, Any], edited: bool = True) -> None:
    tl["edited"] = edited
    tl["saved_at"] = utc_now()
    tl["duration"] = timeline_end(tl)
    write_json(path(ep), tl)


def timeline_end(tl: dict[str, Any]) -> float:
    ends = [c["start"] + c["duration"] for track in ("video", "speech") for c in tl.get(track, [])]
    return round(max(ends, default=0.0), 3)


def make_bumpers(ep: Episode, title: str) -> tuple[str, str]:
    v = settings()["video"]
    intro = ep.path("video", "bumper-intro.mp4")
    outro = ep.path("video", "bumper-outro.mp4")
    if not intro.exists():
        owl.bumper("intro", title, intro, int(v["width"]), int(v["height"]), int(v["fps"]))
    if not outro.exists():
        owl.bumper("outro", title, outro, int(v["width"]), int(v["height"]), int(v["fps"]))
    return ep.rel(intro), ep.rel(outro)


def _fit_lengths(ep: Episode, shots: list[dict[str, Any]], total: float) -> list[float]:
    """Share a scene's time between its shots without repeating anything: animated clips keep about their
    own length (up to a little slow motion), and camera moves and cards stretch or shrink to fill the rest."""
    fixed, flex = {}, []
    for i, s in enumerate(shots):
        if s["clip"].get("still") or s["clip"].get("kind") == "camera_move":
            flex.append(i)
        else:
            try:
                fixed[i] = media.duration(ep.abs(s["clip"]["path"]))
            except Exception:  # noqa: BLE001 - treat an unreadable clip like a still
                flex.append(i)
    lengths = [0.0] * len(shots)
    for i, d in fixed.items():
        lengths[i] = d
    rest = total - sum(fixed.values())
    if flex:
        want = [max(1.5, float(shots[i].get("seconds", 4.0))) for i in flex]
        scale = max(rest, 1.5 * len(flex)) / sum(want)
        for i, w in zip(flex, want):
            lengths[i] = max(1.5, w * scale)
    elif fixed and rest > 0:   # only animated clips: slow them a little (smoothly), then hold the last frame
        factor = total / sum(fixed.values())
        for i in fixed:
            lengths[i] = fixed[i] * factor
    elif fixed and rest < 0:   # too much footage: trim clips evenly
        factor = total / sum(fixed.values())
        for i in fixed:
            lengths[i] = max(1.0, fixed[i] * factor)
    return lengths


def _cut_on_words(ep: Episode, shots: list[dict[str, Any]], words: list[dict[str, Any]], scene_len: float
                  ) -> list[float] | None:
    """How long each shot stays on screen so that each picture comes on as Owlbert starts saying its own words
    (its 'covers'), and the cards at the end of the scene keep their time. None when the words or their timings
    aren't there (the old even split is used), or when an animated clip would have to stretch more than it can
    (it slows to 1.35x at most, then holds its last frame)."""
    pics = [s for s in shots if s.get("kind") != "card"]
    cards = shots[len(pics):]
    if not words or len(pics) < 2 or any(s.get("kind") == "card" for s in shots[:len(pics)]) \
            or not all(s.get("covers") for s in pics):
        return None
    norm = [re.sub(r"[^a-z0-9]", "", w["word"].lower()) for w in words]
    starts, at = [0.0], 0
    for s in pics[1:]:
        want = [x for x in (re.sub(r"[^a-z0-9]", "", w.lower()) for w in s["covers"].split()[:3]) if x]
        found = next((i for i in range(at, len(norm) - len(want) + 1) if want and norm[i:i + len(want)] == want), None)
        if found is None:
            return None
        at = found + 1
        starts.append(LEAD + float(words[found]["start"]) - 0.15)   # the cut lands just before the words
    card_time = sum(float(c.get("seconds") or 4.0) for c in cards)
    pic_len = scene_len - card_time
    on_screen = [b - a for a, b in zip(starts, starts[1:])] + [pic_len - starts[-1]]
    if min(on_screen) < 1.0:
        return None
    for s, length in zip(pics, on_screen):
        clip = s.get("clip") or {}
        if not clip.get("still") and clip.get("kind") != "camera_move":
            try:
                if length > media.duration(ep.abs(clip["path"])) * 1.35 + 1.5:
                    return None
            except Exception:  # noqa: BLE001 - an unreadable clip: use the even split
                return None
    # each shot's length includes the cross-fade it shares with the next one (the timeline overlaps them)
    out = [x + FADE for x in on_screen] + [float(c.get("seconds") or 4.0) + FADE for c in cards]
    out[-1] -= FADE          # the scene takes the same time as before: the last one shares no fade inside it
    return out


def assemble(ep: Episode, progress=lambda t, p=None: None) -> dict[str, Any]:
    script = load_script(ep)
    narration = read_json(ep.path("audio", "narration.json"), {}) or {}
    plan = load_plan(ep)
    if not plan["shots"]:
        raise StageError("Make and approve the video clips first.")
    if not narration:
        raise StageError("Make Owlbert's speech track first (press Make speech track).")
    progress("Making the intro and outro bumpers", 10)
    intro, outro = make_bumpers(ep, script["title"] or ep.title)
    v = settings()["video"]
    tl: dict[str, Any] = {"fps": int(v["fps"]), "width": int(v["width"]), "height": int(v["height"]),
                          "video": [], "speech": [], "music": [], "owl": []}
    t = 0.0
    intro_len = media.duration(ep.abs(intro))
    tl["video"].append({"id": "intro", "src": intro, "start": 0.0, "duration": round(intro_len, 3),
                        "inpoint": 0.0, "label": "Intro bumper", "kind": "bumper", "ai": False, "scene_id": "INTRO"})
    t = intro_len - SCENE_FADE
    word_times = _words(ep)
    by_scene: dict[str, list[dict[str, Any]]] = {}
    for s in plan["shots"]:
        by_scene.setdefault(s["scene_id"], []).append(s)
    progress("Lining the clips up with Owlbert's voice", 50)
    for sc in script["scenes"]:
        m = narration.get(sc["scene_id"])
        shots = [s for s in by_scene.get(sc["scene_id"], []) if s.get("clip")]
        if not shots:
            continue
        scene_len = (LEAD + m["seconds"] + TAIL) if m else sum(s["seconds"] for s in shots)
        lengths = _fit_lengths(ep, shots, scene_len + FADE * (len(shots) - 1))
        on_cue = _cut_on_words(ep, shots, word_times.get(sc["scene_id"], []), scene_len) if m else None
        if on_cue:   # each picture comes on as Owlbert starts saying its words (shotplan.segments)
            lengths = on_cue
        if m:
            tl["speech"].append({"id": f"say-{sc['scene_id']}", "src": m["path"], "start": round(t + LEAD, 3),
                                 "duration": round(m["seconds"], 3), "scene_id": sc["scene_id"],
                                 "text": sc["narration"]})
            if settings()["owl"]["presenter"]:
                tl["owl"].append({"id": f"owl-{sc['scene_id']}", "start": round(t + LEAD, 3),
                                  "duration": round(m["seconds"], 3)})
        for k, (s, length) in enumerate(zip(shots, lengths)):
            last = k == len(shots) - 1
            overlap = SCENE_FADE if last else FADE
            dur = length + (SCENE_FADE - FADE if last else 0.0)
            item = {"id": s["shot_id"], "src": s["clip"]["path"], "start": round(t, 3),
                    "duration": round(dur, 3), "inpoint": 0.0, "label": s["shot_id"],
                    "kind": "clip", "ai": bool(s["clip"].get("ai")), "recreation": bool(s["clip"].get("recreation")),
                    "scene_id": sc["scene_id"]}
            if s.get("kind") == "owl":       # Owlbert is in this shot, so the corner Owlbert steps aside
                item["owl_shot"] = True
                if s.get("owl_live"):
                    item["owl_live"] = s["owl_live"]
            if s["clip"].get("still"):  # camera moves are redrawn at exactly this length when rendering
                item["still"], item["camera"] = s["clip"]["still"], s["clip"].get("camera", "zoom_in")
                if s["clip"].get("depth"):          # a 2.5D move: redrawn with its depth at the exact length
                    item["depth"] = s["clip"]["depth"]
            tl["video"].append(item)
            t += dur - overlap
    outro_len = media.duration(ep.abs(outro))
    tl["video"].append({"id": "outro", "src": outro, "start": round(t, 3), "duration": round(outro_len, 3),
                        "inpoint": 0.0, "label": "Outro bumper", "kind": "bumper", "ai": False, "scene_id": "OUTRO"})
    end = t + outro_len
    music = read_json(ep.path("audio", "music", "music.json"))
    music_ok = ep.stage_status("music")["status"] == "approved" and not \
        (ep.stage_status("music").get("note") or "").startswith("SKIPPED")
    if music and music_ok and music.get("cues"):
        tl["music"] = music_track(ep, tl, script, music["cues"], end)
    elif music and music_ok and ep.abs(music["path"]).exists():
        tl["music"].append({"id": "music", "src": music["path"], "start": 0.0, "duration": round(end, 3),
                            "volume": 1.0})
    tl["moves"] = plan_moves(ep, tl, script)
    tl["sfx"] = sfx_track(ep, tl, script, music.get("cues", []) if music and music_ok else [])
    return tl


CROSSFADE = 2.0                       # seconds two cues overlap
ENERGY_GAIN = {1: 0.7, 2: 0.85, 3: 1.0, 4: 1.12, 5: 1.25}


def _words(ep: Episode) -> dict[str, list[dict[str, Any]]]:
    return {k: v.get("words", []) for k, v in
            ((read_json(ep.path("captions", "words.json"), {}) or {}).get("scenes", {}) or {}).items()}


def _sentence_end(words: list[dict[str, Any]], start: float) -> float:
    for w in words:
        if w["start"] >= start and w["word"].rstrip('"”’)').endswith((".", "!", "?")):
            return float(w["end"])
    return float(words[-1]["end"]) if words else start + 3.0


def music_track(ep: Episode, tl: dict[str, Any], script: dict[str, Any], cues: list[dict[str, Any]],
                end: float) -> list[dict[str, Any]]:
    """Lay the music cues along the timeline: each starts where its first scene starts (a sting or hard cut
    lands on the word), cross-fades into the next, drops out before a 'drop before' line so the voice
    arrives alone, and the last one carries on under the outro."""
    roles = {sc["scene_id"]: sc.get("role", "") for sc in script.get("scenes", [])}
    timing = {sc["scene_id"]: sc for sc in bits.scenes_from_timeline(tl, roles)}
    words = _words(ep)
    out: list[dict[str, Any]] = []
    starts = []
    for k, cue in enumerate(cues):
        first = timing.get(cue["scenes"][0])
        if not first:
            starts.append(None)
            continue
        t = 0.0 if k == 0 else first["start"] - CROSSFADE / 2
        if cue.get("change") in ("sting", "hard_cut"):
            t = first["speech_start"]
            for mark in cue.get("marks", []):
                if mark.get("sting_at") and mark["scene_id"] == first["scene_id"]:
                    at = bits.word_time(mark["sting_at"], words.get(first["scene_id"], []))
                    if at is not None:
                        t = first["speech_start"] + at
        starts.append(max(0.0, t))
    for k, cue in enumerate(cues):
        t0 = starts[k]
        if t0 is None or cue.get("silence") or not cue.get("path"):
            continue
        nxt = next((x for x in starts[k + 1:] if x is not None), None)
        t1 = end if nxt is None else nxt + (0.3 if cues[k + 1].get("change") in ("sting", "hard_cut") else CROSSFADE)
        hard_in = cue.get("change") in ("sting", "hard_cut") and k > 0
        gain = ENERGY_GAIN.get(int(cue.get("energy", 3)), 1.0) * (1.15 if cue.get("mood") == "theme" else 1.0)
        pieces = [(t0, t1)]
        for mark in cue.get("marks", []):                 # music out before a key line, back after it
            if not mark.get("drop_before"):
                continue
            sc = timing.get(mark["scene_id"])
            at = bits.word_time(mark["drop_before"], words.get(mark["scene_id"], [])) if sc else None
            if at is None:
                continue
            cut = sc["speech_start"] + at - 0.25
            back = sc["speech_start"] + _sentence_end(words.get(mark["scene_id"], []), at) + 0.6
            if roles.get(mark["scene_id"]) == "verdict":
                back = sc["end"] + 0.5                     # after the verdict, only the next cue comes in
            new = []
            for a, b in pieces:
                if a < cut < b:
                    new.append((a, cut))
                    if back < b - 1.0:
                        new.append((back, b))
                else:
                    new.append((a, b))
            pieces = new
        for j, (a, b) in enumerate(pieces):
            out.append({"id": f"music-{cue['cue_id']}-{j}", "src": cue["path"], "start": round(a, 3),
                        "duration": round(b - a, 3), "inpoint": round(a - t0, 3), "volume": round(gain, 3),
                        "fade_in": 0.05 if (hard_in and j == 0) else (0.4 if k == 0 and j == 0 else
                                                                     CROSSFADE if j == 0 else 1.5),
                        "fade_out": 4.0 if b >= end - 0.01 else (0.6 if j < len(pieces) - 1 else CROSSFADE),
                        "label": f"Music: {cue['mood']}" + (f" (energy {cue['energy']})" if cue.get("energy") else ""),
                        "cue": cue["cue_id"]})
    return out


def sfx_track(ep: Episode, tl: dict[str, Any], script: dict[str, Any], cues: list[dict[str, Any]]) -> list[dict]:
    """Sound effects: whooshes, pops and sparkles for Owlbert's moves, and a musical sting on each
    'sting at' line (made by fofstudio/sfx.py, so they're ours)."""
    from .. import sfx
    out: list[dict[str, Any]] = []
    for mv in tl.get("moves", []):
        for name, dt in sfx.MOVE_SOUNDS.get(mv["kind"], []):
            out.append({"id": f"sfx-{mv['id']}-{name}-{len(out)}", "src": str(sfx.path(name)),
                        "start": round(mv["start"] + dt, 3), "volume": 0.35, "label": name})
    roles = {sc["scene_id"]: sc.get("role", "") for sc in script.get("scenes", [])}
    timing = {sc["scene_id"]: sc for sc in bits.scenes_from_timeline(tl, roles)}
    words = _words(ep)
    for cue in cues:
        for mark in cue.get("marks", []):
            sc = timing.get(mark["scene_id"])
            if not (mark.get("sting_at") and sc):
                continue
            at = bits.word_time(mark["sting_at"], words.get(mark["scene_id"], []))
            if at is None:
                continue
            name = "sting_minor" if cue.get("mood") in ("tense", "somber", "investigative") else "sting"
            out.append({"id": f"sfx-sting-{mark['scene_id']}", "src": str(sfx.path(name)),
                        "start": round(max(0.0, sc["speech_start"] + at - 0.05), 3), "volume": 0.45,
                        "label": "Sting"})
    out.sort(key=lambda x: x["start"])
    for x in out:
        x["duration"] = 1.0
    return out


def plan_moves(ep: Episode, tl: dict[str, Any], script: dict[str, Any]) -> list[dict[str, Any]]:
    """Owlbert's moves for this video (none if they're switched off in Settings)."""
    o = settings()["owl"]
    if not (o.get("moves", True) and o.get("presenter", True)):
        return []
    roles = {sc["scene_id"]: sc.get("role", "") for sc in script.get("scenes", [])}
    try:
        from .stories import chosen
        tricks = (chosen(ep) or {}).get("techniques", [])
    except Exception:  # noqa: BLE001 - an older project without a chosen story still gets its moves
        tricks = []
    scenes = bits.scenes_from_timeline(tl, roles)
    by_id = {sc["scene_id"]: sc for sc in script.get("scenes", [])}
    if not any(sc.get("owlbert") for sc in by_id.values()):
        return away_from_owl_shots(tl, bits.plan(scenes, ep.creative(), tricks, ep.project_id))
    words = (read_json(ep.path("captions", "words.json"), {}) or {}).get("scenes", {})
    for sc in scenes:
        src = by_id.get(sc["scene_id"], {})
        sc["directions"] = src.get("owlbert", [])
        sc["source_ids"] = src.get("source_ids", [])
        sc["words"] = (words.get(sc["scene_id"]) or {}).get("words", [])
    return away_from_owl_shots(tl, bits.plan_directed(scenes, ep.creative(), tricks, prop_info(ep, by_id)))


def owl_shot_ranges(tl: dict[str, Any], painted_only: bool = False) -> list[tuple[float, float]]:
    """When a shot shows Owlbert. painted_only: just the older shots with him painted into the picture
    (a live one can simply leave the set empty while a move plays)."""
    return [(c["start"], c["start"] + c["duration"]) for c in tl.get("video", [])
            if c.get("owl_shot") and not (painted_only and c.get("owl_live"))]


def away_from_owl_shots(tl: dict[str, Any], moves: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only one Owlbert on screen: a move that would play while a shot has him painted in slides to just
    after that shot, or is dropped. (On live Owlbert shots the move wins and the set stays empty meanwhile.)"""
    busy = owl_shot_ranges(tl, painted_only=True)
    out: list[dict[str, Any]] = []
    for m in moves:
        for _ in range(3):
            hit = next(((a, b) for a, b in busy if m["start"] < b and m["start"] + m["duration"] > a), None)
            if not hit:
                break
            m = {**m, "start": round(hit[1] + 0.2, 3)}
        else:
            continue
        if any(m["start"] < b and m["start"] + m["duration"] > a for a, b in busy):
            continue
        if out and m["start"] < out[-1]["start"] + out[-1]["duration"] + 0.3:
            continue
        out.append(m)
    return out


def prop_info(ep: Episode, scenes: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    """What the document from Owlbert's hat says (the scene's first source) and the verdict word for the stamp."""
    packet = read_json(ep.path("research.json")) or {}
    sources = {s["source_id"]: s for c in packet.get("claims", []) for s in c.get("sources", [])}
    verdict = {c["claim_id"]: c.get("falsity_status", "") for c in packet.get("claims", [])}
    out: dict[str, dict[str, str]] = {}
    for sid, sc in scenes.items():
        info: dict[str, str] = {}
        src = next((sources[x] for x in sc.get("source_ids", []) if x in sources), None)
        if src:
            title = (src.get("title") or "The record")[:90]
            when = " · ".join(x for x in (src.get("publisher"), src.get("date")) if x)
            info["document"] = f"{title}|{when}"
        v = next((verdict[c] for c in sc.get("claim_ids", []) if c in verdict), "") or \
            next(iter(verdict.values()), "")
        info["verdict"] = bits.VERDICT_WORDS.get(str(v).lower().replace(" ", "_"), str(v).upper() or "VERDICT")
        out[sid] = info
    return out


def _stale_reason(ep: Episode, tl: dict[str, Any]) -> str:
    """Why an edited timeline no longer matches the clips and speech (empty if it still does)."""
    missing = [c for track in ("video", "speech", "music") for c in tl.get(track, []) if not ep.abs(c["src"]).exists()]
    if missing:
        return f"{len(missing)} of its files are gone (remade or cleared)"
    plan = {s["shot_id"]: s["clip"]["path"] for s in load_plan(ep)["shots"] if s.get("clip")}
    on = {c["id"]: c["src"] for c in tl.get("video", []) if c.get("kind") == "clip"}
    if plan and (set(plan) != set(on) or any(plan[k] != on[k] for k in plan if k in on)):
        return "the video clips changed"
    narration = read_json(ep.path("audio", "narration.json"), {}) or {}
    said = {c["scene_id"]: c["src"] for c in tl.get("speech", [])}
    if narration and {k: v["path"] for k, v in narration.items()} != said:
        return "Owlbert's speech track changed"
    return ""


def run(ctx: Context) -> None:
    ep = ctx.episode
    existing = load(ep)
    if existing.get("edited") and not ctx.options.get("rebuild"):
        stale = _stale_reason(ep, existing)
        if not stale:
            ctx.progress("Keeping your edited timeline (choose Rebuild to start over).", 100)
            return
        ctx.log(f"Rebuilt the timeline: {stale}, so your earlier edits no longer fit.")
    tl = assemble(ep, ctx.progress)
    save(ep, tl, edited=False)
    ctx.progress(f"Timeline ready: {timeline_end(tl) / 60:.1f} minutes. Preview it, adjust, then render.", 100)


def check(ep: Episode) -> list[Check]:
    tl = load(ep)
    if not tl:
        return [Check(BLOCK, "No timeline yet. Press Assemble timeline.")]
    out: list[Check] = []
    missing = [c["label"] if "label" in c else c["id"] for track in ("video", "speech", "music")
               for c in tl.get(track, []) if not ep.abs(c["src"]).exists()]
    if missing:
        out.append(Check(BLOCK, f"Files missing from the timeline: {', '.join(missing[:6])}"))
    narration = read_json(ep.path("audio", "narration.json"), {}) or {}
    on_track = {c["scene_id"] for c in tl.get("speech", [])}
    lost = [s for s in narration if s not in on_track]
    if lost:
        out.append(Check(BLOCK, f"Owlbert's lines for {', '.join(lost)} aren't on the speech track. Rebuild."))
    for c in tl.get("speech", []):
        m = narration.get(c["scene_id"])
        if m and m["path"] != c["src"]:
            out.append(Check(BLOCK, f"{c['scene_id']}: the speech track uses an old recording. Rebuild."))
    video = sorted(tl.get("video", []), key=lambda c: c["start"])
    for a, b in zip(video, video[1:]):
        gap = b["start"] - (a["start"] + a["duration"])
        if gap > 0.3:
            out.append(Check(WARN, f"{gap:.1f} s of black between {a['label']} and {b['label']}."))
    end_v = max((c["start"] + c["duration"] for c in video), default=0)
    end_s = max((c["start"] + c["duration"] for c in tl.get("speech", [])), default=0)
    if end_s > end_v:
        out.append(Check(WARN, "Owlbert keeps talking after the picture ends."))
    if not any(c.level == BLOCK for c in out):
        out.append(Check(OK, f"Timeline: {timeline_end(tl) / 60:.1f} min, {len(video)} video clips, "
                             f"{len(tl.get('speech', []))} speech lines. Press Preview to watch it."))
    return out
