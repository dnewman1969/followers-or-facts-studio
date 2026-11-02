"""The film crew between the script and the painter (Dave, 2026-11-02: "we need to think of it like the way a
movie is made, with the script writer, director, scene designer, script supervisor to make sure there are no
continuity errors"; research "AI film crew production pipeline").

On a film set a line of script passes through several people before anything is photographed, each adding one
kind of decision. Before this, one "director" call wrote a sentence per shot and the painter drew that sentence
as it stood, so pictures came out literal: labels and numbers painted in, a red owl the painter invented, plain
grey rooms. Now each job is its own role card - the real profession's job, a fixed answer form, the house rules -
and Python rejects any answer that breaks the rules:

  Breakdown clerk     (bible.make)         every scene's place, people, story beat, what must be seen
  Production designer (design_sets)        dresses each place: era, 6-10 set pieces with materials and wear,
                                           a palette, where the light comes from
  Director            (storyboard._plan_*) what each piece of narration shows, and why
  Layout artist       (controlmaps.guide_for + director.py)  camera size and angle, the matching Unreal camera
  Storyboard artist   (camera_sees)        one frozen moment, written as what the camera sees, from the
                                           approved fields: no numbers, labels, names or owl in it
  Script supervisor   (supervise)          the continuity log: the place, light and owl rules checked shot by
                                           shot before anything is painted
  Animation director  (stages/video.py)    how each shot moves; Owlbert only through his own rig

Every step a crew member takes goes in the crew log (crew.json), with its reason, so the Crew window can show
who did what and why.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .episode import Episode
from .util import read_json, utc_now, write_json

ROLES = [
    {"key": "breakdown", "title": "Breakdown clerk", "real": "1st AD / script supervisor (prep)",
     "job": "Reads the locked script and lists, for every scene, its place, the people in it, the story beat, "
            "the feeling and what must be seen."},
    {"key": "designer", "title": "Production designer", "real": "production designer / set decorator",
     "job": "Dresses every place: its era, 6-10 set pieces with materials and wear, a palette and where the "
            "light comes from, so a room is a designed set and not a grey box."},
    {"key": "director", "title": "Director", "real": "director",
     "job": "Decides what each piece of narration shows and why: the place, the object, the document, the "
            "visual metaphor, and the feeling."},
    {"key": "layout", "title": "Layout artist", "real": "cinematographer / layout artist",
     "job": "Chooses each shot's size, angle and camera move, keeps variety between neighbours, and picks the "
            "matching Unreal camera for the room's layout."},
    {"key": "artist", "title": "Storyboard artist", "real": "storyboard artist",
     "job": "Turns each planned shot into one frozen moment, written as what the camera sees, with the set's "
            "real details. Never numbers, labels, names or a painted owl."},
    {"key": "supervisor", "title": "Script supervisor", "real": "script supervisor (continuity)",
     "job": "Keeps the continuity log and checks every shot before it is painted: same place, same light, "
            "Owlbert only where he belongs, nothing that would be painted as text."},
    {"key": "animation", "title": "Animation director", "real": "animation director",
     "job": "Chooses how each picture moves (an animated clip or a slow 2.5D camera move) and writes one clear "
            "action; Owlbert moves only through his own rig."},
    {"key": "dave", "title": "You (showrunner)", "real": "director / showrunner",
     "job": "Approve each step: the script, the pictures, the clips, the cut. Overrule any crew choice."},
]
TITLE = {r["key"]: r["title"] for r in ROLES}

# what the painter must never be handed (a whitelist check, after the writer: research "AI film crew production
# pipeline"): numbers, colons and quotes are painted as text; Owlbert only comes from his own artwork
DIGITS = re.compile(r"\S*\d\S*")
QUOTES = re.compile(r"[\"“”‘’«»]|(?<!\w)'|'(?!\w)")
STAGING = re.compile(r"\b(?:the\s+shot\s+(?:begins|opens|ends)|the\s+camera\s+(?:begins|starts)|then\b|enters?\b|"
                     r"exits?\b|walks\s+(?:to|into|in)\b|beat\b|cut\s+to\b)", re.I)


_TENS = {"2": "twenties", "3": "thirties", "4": "forties", "5": "fifties", "6": "sixties", "7": "seventies",
         "8": "eighties", "9": "nineties", "0": "two-thousands", "1": "twenty-tens"}
_FILM = {"8": "eight", "16": "sixteen", "35": "thirty-five", "65": "sixty-five", "70": "seventy"}


def numbers_as_words(text: str) -> str:
    """Numbers that carry meaning in a look ("1980s", "35mm") said in words, so they survive the no-digits rule."""
    t = re.sub(r"\b1[89](\d)0s\b", lambda m: "nineteen-" + _TENS[m.group(1)], text or "")
    t = re.sub(r"\b20([01])0s\b", lambda m: _TENS["0" if m.group(1) == "0" else "1"], t)
    t = re.sub(r"\b'?(\d)0s\b", lambda m: _TENS[m.group(1)], t)
    t = re.sub(r"\b(8|16|35|65|70)\s?mm\b", lambda m: _FILM[m.group(1)] + " millimetre", t, flags=re.I)
    return t


def log(ep: Episode, role: str, what: str, shot: str = "") -> None:
    """One line in the crew log (newest last, the last 3000 kept)."""
    p = ep.path("crew.json")
    entries = read_json(p, []) or []
    entries.append({"at": utc_now(), "role": role, "who": TITLE.get(role, role), "shot": shot, "what": what[:400]})
    write_json(p, entries[-3000:])


def entries(ep: Episode) -> list[dict[str, Any]]:
    return read_json(ep.path("crew.json"), []) or []


def _owl_words():
    from .stages.storyboard import OWLBERT_WORDS, OWL_WORDS
    return OWLBERT_WORDS, OWL_WORDS


def painter_safe(text: str, owl_allowed: bool = False) -> str:
    """The last check before the painter: no numbers, quotes, labels, ratios, staging words or real names; no
    owl or bird unless it's an Owlbert shot (and even then only the empty set is painted)."""
    from .promptcheck import clean_prompt, no_text_cues
    from .stages.storyboard import names_in, person_names
    t = numbers_as_words(no_text_cues(text or ""))
    t = DIGITS.sub("", t)
    t = QUOTES.sub("", t)
    t = t.replace(":", ",")
    t = STAGING.sub("", t)
    named, owlish = _owl_words()
    if not owl_allowed:
        t = named.sub("", t)
        t = re.sub(r"\b(?:owls?|birds?|beaks?|feathers?|wings?)\b", "", t, flags=re.I)
    for n in names_in(t, person_names()):
        t = re.sub(rf"\b{re.escape(n)}(?:'s)?\b", "an anonymous figure", t, flags=re.I)
    t, _ = clean_prompt(t)
    t = re.sub(r"\s+([,.;])", r"\1", t)
    t = re.sub(r"([,.;])\s*(?=[,.;])", "", t)
    return re.sub(r"\s{2,}", " ", t).strip(" ,;.")


# ---------------------------------------------------------------- production designer
DESIGN_SCHEMA = {"type": "object", "properties": {"places": {"type": "array", "items": {
    "type": "object", "properties": {
        "id": {"type": "string"}, "era": {"type": "string"},
        "dressing": {"type": "array", "minItems": 6, "maxItems": 10, "items": {"type": "string"}},
        "palette": {"type": "string"}, "light_from": {"type": "string"}, "light_source": {"type": "string"}},
    "required": ["id", "era", "dressing", "palette", "light_from", "light_source"]}}}, "required": ["places"]}


def design_sets(ep: Episode, bible: dict[str, Any], style, llm=None, log_line=lambda m: None,
                on_text=None) -> dict[str, Any]:
    """The production designer dresses every place in the bible once (kept until the bible changes)."""
    locs = bible.get("locations") or {}
    todo = [loc for loc in locs.values() if not loc.get("dressing")]
    if not todo:
        return bible
    if llm is None:
        from .llm import Ollama
        llm = Ollama(job="storyboard")
    places = [{k: loc.get(k, "") for k in ("id", "name", "architecture", "colours", "lighting", "textures", "props")}
              for loc in todo]
    try:
        ans = llm.chat_json([
            {"role": "system", "content": (
                "You are the production designer and set decorator of a documentary drawn in this look: "
                f"{style.look}. For every place, design the set the camera will see: its era; 6 to 10 concrete set "
                "pieces, each with its material and its wear (for example 'cracked green leather armchair', 'brass "
                "desk lamp with a dented shade', 'stacked yellowed newspapers', 'rain-streaked window with venetian "
                "blinds'); a palette of two or three colours; where the light comes from (left, right, behind, "
                "above) and what makes it (a window, a lamp, a screen). Only physical things the camera sees. No "
                "signs, posters, screens or papers with readable words, no numbers, no people, no animals, no "
                "birds, no real names, no brand names.")},
            {"role": "user", "content": json.dumps({"places": places}, ensure_ascii=False)}],
            DESIGN_SCHEMA, lenient=True, temperature=0.4, on_text=on_text)
    except Exception as exc:  # noqa: BLE001 - the places keep the bible's own words; said in the log
        log_line(f"Production designer couldn't dress the sets ({exc}); the bible's descriptions are used")
        log(ep, "designer", f"couldn't dress the sets: {exc}")
        return bible
    by_id = {str(p.get("id", "")).strip(): p for p in ans.get("places") or []}
    for i, loc in enumerate(todo):
        got = by_id.get(loc["id"]) or ((ans.get("places") or [])[i] if i < len(ans.get("places") or []) else None)
        if not got:
            continue
        items = [painter_safe(x) for x in got.get("dressing") or []]
        items = [x for x in items if 2 <= len(x.split()) <= 14][:10]
        if len(items) < 3:
            continue
        loc.update({"era": painter_safe(got.get("era", ""))[:60], "dressing": items,
                    "palette": painter_safe(got.get("palette", ""))[:80],
                    "light": painter_safe(f"light from the {got.get('light_from', '')}, from "
                                          f"{got.get('light_source', '')}")[:100]})
        log(ep, "designer", f"dressed {loc.get('name') or loc['id']}: " + "; ".join(items[:6]))
        log_line(f"Production designer dressed {loc.get('name') or loc['id']} ({len(items)} set pieces)")
    write_json(ep.path("bible.json"), bible)
    return bible


# ---------------------------------------------------------------- storyboard artist
FRAMES_SCHEMA = {"type": "object", "properties": {"frames": {"type": "array", "items": {
    "type": "object", "properties": {"shot_id": {"type": "string"}, "camera_sees": {"type": "string"}},
    "required": ["shot_id", "camera_sees"]}}}, "required": ["frames"]}


def _brief(shot: dict[str, Any]) -> dict[str, Any]:
    look = shot.get("look") or {}
    return {"shot_id": shot["shot_id"], "kind": shot["kind"], "shows": shot.get("shows", ""),
            "planned": shot.get("idea", ""), "feeling": shot.get("emotion", ""),
            "camera": ", ".join(x for x in (look.get("shot_type"), look.get("angle")) if x),
            "light": look.get("lighting", ""), "colour": look.get("palette", ""),
            "pose": look.get("pose", "") if look.get("pose") not in ("", "none") else ""}


def camera_sees(ep: Episode, entry: dict[str, Any], bible: dict[str, Any], style, llm=None,
                log_line=lambda m: None, on_text=None) -> int:
    """The storyboard artist writes each shot of a scene as one frozen moment the camera sees. Returns how many
    shots got a new frame description. Shots keep it until their planned idea changes."""
    from . import bible as biblemod
    todo = [s for s in entry["shots"] if not s.get("by_hand") and s.get("kind") != "real"
            and (not s.get("camera_sees") or s.get("camera_sees_from") != s.get("idea"))]
    if not todo:
        return 0
    if llm is None:
        from .llm import Ollama
        llm = Ollama(job="storyboard")
    sid = entry["scene_id"]
    loc = (bible.get("locations") or {}).get(((bible.get("scenes") or {}).get(sid) or {}).get("location", "")) or {}
    place = {"name": loc.get("name", ""), "era": loc.get("era", ""), "set_pieces": loc.get("dressing", []),
             "palette": loc.get("palette", ""), "light": loc.get("light", "") or loc.get("lighting", "")}
    people = biblemod.character_words(bible, ((bible.get("scenes") or {}).get(sid) or {}).get("characters", []))
    try:
        ans = llm.chat_json([
            {"role": "system", "content": (
                f"You are the storyboard artist of a documentary drawn in this look: {style.look}. For each planned "
                "shot write 'camera_sees': ONE frozen instant, as a painter would see it, in 40 to 110 words, in "
                "this order: the framing; the main subject and exactly what it is doing at this instant; the set "
                "pieces around it (use the place's set pieces, with their materials and wear); the light and time "
                "of day; the colours. Show the moment, don't tell the story: no 'the shot begins', 'then', 'enters', "
                "'walks to'. Never numbers, dates, quotes, captions, labels, signs or readable writing (a document "
                "is 'a typed page', never what it says). Never a real person's name. For kind 'owl' describe ONLY "
                "the empty place where the host will stand (he is added from his own artwork): never an owl or a "
                "bird. For other kinds never an owl or a bird. People are seen from behind or far away, wearing "
                "what the bible gives them.")},
            {"role": "user", "content": json.dumps({
                "place": place, "people": people, "scene_feeling": ((bible.get("scenes") or {}).get(sid) or {}).get(
                    "emotion", ""), "shots": [_brief(s) for s in todo]}, ensure_ascii=False)}],
            FRAMES_SCHEMA, lenient=True, temperature=0.4, on_text=on_text)
    except Exception as exc:  # noqa: BLE001 - the shots are painted from the director's ideas; said in the log
        log_line(f"Storyboard artist couldn't write {sid} ({exc}); painting from the director's ideas")
        log(ep, "artist", f"couldn't write {sid}: {exc}")
        return 0
    got = {str(f.get("shot_id", "")).strip(): f.get("camera_sees", "") for f in ans.get("frames") or []}
    n = 0
    for i, shot in enumerate(todo):
        text = got.get(shot["shot_id"]) or ((ans.get("frames") or [])[i].get("camera_sees", "")
                                            if i < len(ans.get("frames") or []) else "")
        safe = painter_safe(text, owl_allowed=False)
        if len(safe.split()) < 8:
            log(ep, "artist", "no usable frame description; the director's idea is used", shot["shot_id"])
            continue
        shot["camera_sees"], shot["camera_sees_from"] = safe, shot.get("idea")
        log(ep, "artist", safe[:240], shot["shot_id"])
        n += 1
    if n:
        log_line(f"Storyboard artist drew up {n} frame(s) for {sid}")
    return n


# ---------------------------------------------------------------- script supervisor
def supervise(ep: Episode, planned: list[dict[str, Any]], bible: dict[str, Any], log_line=lambda m: None
              ) -> list[str]:
    """The script supervisor's check before painting. Fixes what can be fixed (it says so), notes the rest."""
    named, _ = _owl_words()
    notes: list[str] = []
    for entry in planned:
        sid = entry["scene_id"]
        place = ((bible.get("scenes") or {}).get(sid) or {}).get("location", "")
        prev = None
        for shot in entry["shots"]:
            if shot.get("by_hand"):
                prev = shot
                continue
            text = shot.get("camera_sees") or shot.get("idea", "")
            if shot["kind"] not in ("owl",) and named.search(text):
                shot["camera_sees"] = painter_safe(text)
                notes.append(f"{shot['shot_id']}: Owlbert was in a scene shot; taken out (he's never painted)")
            if DIGITS.search(shot.get("camera_sees", "")):
                shot["camera_sees"] = painter_safe(shot["camera_sees"])
                notes.append(f"{shot['shot_id']}: numbers taken out (they'd be painted as text)")
            look, plook = shot.get("look") or {}, (prev or {}).get("look") or {}
            if prev and look.get("shot_type") and look.get("shot_type") == plook.get("shot_type") \
                    and look.get("angle") == plook.get("angle") and shot.get("shows") == prev.get("shows"):
                notes.append(f"{shot['shot_id']}: same size, angle and subject as the shot before (a jump cut)")
            shot.setdefault("continuity", {})
            shot["continuity"] = {"place": place, "light": ((bible.get("locations") or {}).get(place) or {}).get(
                "light", ""), "owlbert": "rig" if shot["kind"] == "owl" else "none"}
            prev = shot
    for n in notes:
        log(ep, "supervisor", n.split(": ", 1)[1], n.split(":", 1)[0])
    log(ep, "supervisor", f"checked {sum(len(e['shots']) for e in planned)} shots; {len(notes)} note(s)")
    if notes:
        log_line(f"Script supervisor: {len(notes)} note(s), e.g. {notes[0]}")
    return notes
