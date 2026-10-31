"""Script Analysis: the film's bible, made before any picture (Dave's brief, 2026-10-31).

The local AI reads the whole approved script once and writes:
  * a LOCATION bible: every place the video shows (architecture, colours, weather, light, textures, props),
    and which place each scene is in, so a place looks the same every time it comes back;
  * a CHARACTER bible: who appears on screen and how they're drawn. On this channel that's
      - Owlbert (always his real artwork, never painted),
      - public figures who sold the lie: ONLY their approved caricature design (cast.py), never described here,
      - anonymous figures the story needs (a radio listener, a shop clerk, a crowd), always seen from behind
        or far away, with fixed clothing and colours so they stay the same person from shot to shot.
    Never victims, families or children: they aren't characters in any form (the editorial rules);
  * per scene: the story beat, the emotional beat, the key objects and documents, what must be seen.
Every storyboard prompt then uses the scene's location and its characters' fixed descriptions, so places and
people stop changing look. The bible is saved as bible.json and can be edited.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .episode import Episode
from .util import read_json, utc_now, write_json

EMOTIONS = ["fear", "tension", "joy", "hope", "mystery", "excitement", "sadness", "anger", "curiosity", "calm",
            "resolve"]
BIBLE_SCHEMA = {"type": "object", "properties": {
    "locations": {"type": "array", "maxItems": 12, "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "name": {"type": "string"}, "architecture": {"type": "string"},
        "colours": {"type": "string"}, "weather": {"type": "string"}, "lighting": {"type": "string"},
        "textures": {"type": "string"}, "props": {"type": "string"}},
        "required": ["id", "name", "architecture", "colours", "lighting", "props"]}},
    "characters": {"type": "array", "maxItems": 8, "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "role": {"type": "string"}, "clothing": {"type": "string"},
        "hair": {"type": "string"}, "build": {"type": "string"}, "identifiers": {"type": "string"}},
        "required": ["id", "role", "clothing", "identifiers"]}},
    "scenes": {"type": "array", "items": {"type": "object", "properties": {
        "scene_id": {"type": "string"}, "location": {"type": "string"},
        "characters": {"type": "array", "items": {"type": "string"}},
        "story_beat": {"type": "string"}, "emotion": {"type": "string", "enum": EMOTIONS},
        "must_show": {"type": "array", "items": {"type": "string"}, "maxItems": 4}},
        "required": ["scene_id", "location", "characters", "story_beat", "emotion", "must_show"]}}},
    "required": ["locations", "characters", "scenes"]}
NEVER = re.compile(r"\b(?:victims?|child|children|kids?|boy|girl|baby|babies|families|family|widow\w*|mourner\w*|"
                   r"survivors?|parents?|teen\w*|minors?|student\w*)\b", re.I)
BODY = re.compile(r"\b(?:skin|complexion|weight|fat|obese|overweight|chubby|skinny|race|racial|ethnic\w*|"
                  r"religio\w*|disab\w*|ugly)\b", re.I)


def path(ep: Episode):
    return ep.path("bible.json")


def load(ep: Episode) -> dict[str, Any]:
    return read_json(path(ep), {}) or {}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")[:30] or "place"


def make(ep: Episode, script: dict[str, Any], llm=None, on_text=None) -> dict[str, Any]:
    """Read the script and write the bible (or keep the one you edited, if the script hasn't changed)."""
    from .stages.storyboard import names_in, person_names
    old = load(ep)
    key = json.dumps([(s["scene_id"], s.get("visual"), s.get("narration")) for s in script["scenes"]])
    if old and old.get("script_key") == key:
        return old
    if llm is None:
        from .llm import Ollama
        llm = Ollama(job="storyboard")
    scenes_in = [{"scene_id": s["scene_id"], "role": s.get("role", ""), "visual_note": s.get("visual", ""),
                  "narration": s.get("narration", "")[:700]} for s in script["scenes"]]
    try:
        ans = llm.chat_json([
            {"role": "system", "content": (
                "You are the script supervisor and production designer of a fact-check documentary. Read the whole "
                "script and write the film's bible. LOCATIONS: the real places the story happens (a radio studio, a "
                "small-town main street, a county courthouse, a warehouse...) and metaphor spaces only where the "
                "script needs them; for each: architecture, colours, weather, lighting, textures and props, in short "
                "visual words, so it can be drawn the same every time. CHARACTERS: only anonymous figures the "
                "pictures need (a listener at a kitchen radio, a clerk, a crowd), always seen from behind or far "
                "away, with fixed clothing, hair and build so they stay the same person. Never name or describe a "
                "real person, never a victim, a family member or a child, never skin, weight, age, race or "
                "religion. The host owl and the caricatures are added by the program: don't list them. SCENES: for "
                "every scene_id: its location id, the characters in it (ids), the story beat in one line, the "
                "emotion the audience should feel, and up to 4 things that must be seen (an object, a document, "
                "a place, a number shown as an object).")},
            {"role": "user", "content": json.dumps({"title": script.get("title", ""), "scenes": scenes_in},
                                                   ensure_ascii=False)}],
            BIBLE_SCHEMA, lenient=True, temperature=0.3, on_text=on_text)
    except Exception:  # noqa: BLE001 - the storyboard still works from the scene notes; said in the bible itself
        ans = {}
    names = person_names()

    def ok(text: str) -> bool:
        return bool(text) and not NEVER.search(text) and not names_in(text, names)

    def tidy(text: Any) -> str:
        return BODY.sub("", " ".join(str(text or "").split()))[:160].strip(" ,.")

    locations = {}
    for loc in ans.get("locations") or []:
        lid = _slug(loc.get("id") or loc.get("name"))
        desc = {k: tidy(loc.get(k)) for k in ("name", "architecture", "colours", "weather", "lighting", "textures",
                                               "props")}
        if ok(" ".join(desc.values())) and lid not in locations:
            locations[lid] = {"id": lid, **desc}
    characters = {}
    for ch in ans.get("characters") or []:
        cid = _slug(ch.get("id") or ch.get("role"))
        desc = {k: tidy(ch.get(k)) for k in ("role", "clothing", "hair", "build", "identifiers")}
        if ok(" ".join(desc.values())) and cid not in characters:
            characters[cid] = {"id": cid, **desc, "seen": "from behind or far away"}
    by_scene = {s.get("scene_id"): s for s in ans.get("scenes") or []}
    scenes = {}
    for s in script["scenes"]:
        a = by_scene.get(s["scene_id"]) or {}
        loc = _slug(a.get("location") or "")
        scenes[s["scene_id"]] = {
            "location": loc if loc in locations else "",
            "characters": [c for c in (_slug(x) for x in a.get("characters") or []) if c in characters],
            "story_beat": tidy(a.get("story_beat")) or s.get("visual", "")[:120],
            "emotion": a.get("emotion") if a.get("emotion") in EMOTIONS else "curiosity",
            "must_show": [tidy(x) for x in (a.get("must_show") or [])[:4] if ok(tidy(x))]}
    bible = {"locations": locations, "characters": characters, "scenes": scenes, "script_key": key,
             "made_at": utc_now(), "note": "" if ans else "The local AI couldn't write the bible; scenes use "
                                                          "their own notes."}
    write_json(path(ep), bible)
    return bible


def location_words(bible: dict[str, Any], scene_id: str) -> str:
    """The scene's place, drawn the same way every time it appears."""
    sc = (bible.get("scenes") or {}).get(scene_id) or {}
    loc = (bible.get("locations") or {}).get(sc.get("location") or "")
    if not loc:
        return ""
    parts = [loc.get("name"), loc.get("architecture"), loc.get("colours"), loc.get("weather"), loc.get("lighting"),
             loc.get("textures")]
    return ", ".join(p for p in parts if p)


def character_words(bible: dict[str, Any], ids: list[str]) -> str:
    out = []
    for cid in ids:
        ch = (bible.get("characters") or {}).get(cid)
        if ch:
            bits = [ch.get("role"), ch.get("clothing"), ch.get("hair"), ch.get("build"), ch.get("identifiers"),
                    "seen from behind or far away"]
            out.append(", ".join(b for b in bits if b))
    return "; ".join(out)


def for_prompt(bible: dict[str, Any], scene_id: str) -> str:
    """What the shot planner is told about this scene from the bible."""
    sc = (bible.get("scenes") or {}).get(scene_id) or {}
    if not sc:
        return ""
    lines = [f"Story beat: {sc.get('story_beat', '')}", f"The audience should feel: {sc.get('emotion', '')}"]
    if location_words(bible, scene_id):
        lines.append(f"Location (keep it looking like this): {location_words(bible, scene_id)}")
    chars = {cid: (bible.get("characters") or {}).get(cid, {}).get("role", cid) for cid in sc.get("characters", [])}
    if chars:
        lines.append("Characters available (by id, drawn the same every time, seen from behind or far away): "
                     + ", ".join(f"{k} = {v}" for k, v in chars.items()))
    if sc.get("must_show"):
        lines.append("Must be seen somewhere in this scene: " + "; ".join(sc["must_show"]))
    return "\n".join(lines)
