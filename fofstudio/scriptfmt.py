"""Read and write script.md in truth-vlog's v2 scene format, plus a SOURCES line.

    ## SCENE_001 | claim | ~60s

    ### VISUAL
    ...
    ### NARRATION
    ...
    ### ON_SCREEN_TEXT
    ...
    ### SOURCES
    claims: C-Y2K-PLANT | sources: S-AP-1999-12-31 | quotes: E12
    ### MUSIC
    mood: tense | energy: 3 | change: crossfade | drop before: "Here is exactly what he said"
    ### OWLBERT
    - point at "the memo itself says"
    - hat_trick document at "here's the receipt"

MUSIC tells the music what to do in this scene (see MOODS and CHANGES); OWLBERT lists his moves,
each tied to the words he's saying when it happens. Both are optional.
Older truth-vlog scripts without the role or SOURCES line still parse.
"""

from __future__ import annotations

import re
from typing import Any

# tell = Owlbert names the trick; toolkit = the question to ask next time
ROLES = ("intro", "claim", "record", "benefit", "harm", "tell", "toolkit", "verdict", "outro", "credits")
SECTIONS = ("VISUAL", "NARRATION", "ON_SCREEN_TEXT", "SOURCES", "MUSIC", "OWLBERT", "CLIP", "NOTES")

# the music's mood in a scene, and how it gets there from the scene before
MOODS = ("curious", "tense", "investigative", "warm", "somber", "playful", "encouraging", "resolved", "theme")
# continue = the same music carries on; crossfade = new music blends in; sting = a short musical hit on
# "sting at", then new music; hard_cut = new music starts on the first word; silence = no music
CHANGES = ("continue", "crossfade", "sting", "hard_cut", "silence")
QUOTED = {"drop before": "drop_before", "back after": "back_after", "sting at": "sting_at"}
# Owlbert's moves (fofstudio/bits.py draws them) and what he can pull out of his hat
MOVES = ("fly_in", "fly_out", "point", "glasses", "think", "hat_tip", "solemn", "surprised", "flourish", "swoop",
         "hat_trick", "stamp",
         "wave", "nod", "shake", "shrug", "facepalm", "magnify", "read", "count", "lean_in", "sigh", "bounce")
PROPS = ("card", "document", "bulb", "magnifier")


def parse_music(text: str) -> dict[str, Any]:
    if not text.strip() or text.strip() == "-":
        return {}
    out: dict[str, Any] = {}
    for part in text.split("|"):
        if ":" not in part:
            continue
        k, v = (x.strip() for x in part.split(":", 1))
        k = k.lower()
        if k == "energy":
            m = re.search(r"\d", v)
            out["energy"] = max(1, min(5, int(m.group(0)))) if m else 2
        elif k == "mood" and v.lower() in MOODS:
            out["mood"] = v.lower()
        elif k == "change" and v.lower() in CHANGES:
            out["change"] = v.lower()
        elif k in QUOTED:
            q = v.strip().strip('"“”').strip()
            if q:
                out[QUOTED[k]] = q
    return out


def render_music(m: dict[str, Any]) -> str:
    if not m:
        return "-"
    parts = [f"mood: {m.get('mood', 'calm')}", f"energy: {m.get('energy', 2)}", f"change: {m.get('change', 'continue')}"]
    for label, key in QUOTED.items():
        if m.get(key):
            parts.append(f'{label}: "{m[key]}"')
    return " | ".join(parts)


def parse_owlbert(text: str) -> list[dict[str, str]]:
    out = []
    for line in text.splitlines():
        line = line.strip().lstrip("-*• ").strip()
        m = re.match(r"([a-z_]+)(?:\s+([a-z]+))?(?:\s+at\s+[\"“](.+?)[\"”])?\s*$", line, re.IGNORECASE)
        if not m or m.group(1).lower() not in MOVES:
            continue
        d = {"move": m.group(1).lower()}
        if m.group(2) and m.group(2).lower() in PROPS:
            d["prop"] = m.group(2).lower()
        if m.group(3):
            d["at"] = m.group(3).strip()
        out.append(d)
    return out


def render_owlbert(moves: list[dict[str, str]]) -> str:
    lines = []
    for d in moves or []:
        line = "- " + d["move"] + (f" {d['prop']}" if d.get("prop") else "")
        if d.get("at"):
            line += f' at "{d["at"]}"'
        lines.append(line)
    return "\n".join(lines) or "-"


def _ids(text: str, key: str) -> list[str]:
    m = re.search(rf"{key}\s*:\s*([^|\n]*)", text, re.IGNORECASE)
    if not m:
        return []
    return [p.strip() for p in re.split(r"[,;\s]+", m.group(1)) if p.strip() and p.strip() != "-"]


def parse(text: str) -> dict[str, Any]:
    title_m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    scenes = []
    for block in re.split(r"(?m)^(?=## SCENE_)", text):
        head = re.match(r"## (SCENE_\w+)(.*)", block)
        if not head:
            continue
        scene_id = head.group(1)
        extra = head.group(2)
        role_m = re.search(r"\|\s*([a-z_]+)\s*(?:\||$)", extra)
        secs_m = re.search(r"~\s*(\d+)\s*s", extra)
        fields: dict[str, str] = {}
        for name in SECTIONS:
            m = re.search(rf"^### {name}\s*\n(.*?)(?=^### |^---\s*$|\Z)", block,
                          re.DOTALL | re.MULTILINE)
            if m:
                fields[name] = m.group(1).strip()
        narration = re.sub(r"\s*\n\s*", " ", fields.get("NARRATION", "")).strip()
        narration = re.sub(r"\*\*([^*]+)\*\*", r"\1", narration)
        src = fields.get("SOURCES", "")
        scenes.append({
            "scene_id": scene_id,
            "role": role_m.group(1) if role_m else "",
            "est_seconds": int(secs_m.group(1)) if secs_m else None,
            "visual": fields.get("VISUAL", ""),
            "narration": narration,
            "on_screen_text": fields.get("ON_SCREEN_TEXT", "").strip(),
            "claim_ids": _ids(src, "claims"),
            "source_ids": _ids(src, "sources"),
            "excerpt_ids": [q.lstrip("Ee") for q in _ids(src, "quotes")],
            "music": parse_music(fields.get("MUSIC", "")),
            "owlbert": parse_owlbert(fields.get("OWLBERT", "")),
        })
    return {"title": title_m.group(1).strip() if title_m else "", "scenes": scenes}


def render(title: str, scenes: list[dict[str, Any]], header: dict[str, str] | None = None) -> str:
    lines = [f"# {title}", ""]
    if header:
        lines.append(" · ".join(f"**{k}:** {v}" for k, v in header.items()))
        lines.append("")
    lines += ["Edit this file freely: change words, add or remove scenes. Keep the `## SCENE_###` "
              "headings and the SOURCES lines, then press **Re-check** in the app.", "", "---", ""]
    for sc in scenes:
        est = f" | ~{int(sc['est_seconds'])}s" if sc.get("est_seconds") else ""
        role = f" | {sc['role']}" if sc.get("role") else ""
        lines += [f"## {sc['scene_id']}{role}{est}", "",
                  "### VISUAL", sc.get("visual", "").strip() or "-", "",
                  "### NARRATION", sc.get("narration", "").strip() or "-", "",
                  "### ON_SCREEN_TEXT", sc.get("on_screen_text", "").strip() or "-", "",
                  "### SOURCES",
                  f"claims: {', '.join(sc.get('claim_ids') or []) or '-'} | "
                  f"sources: {', '.join(sc.get('source_ids') or []) or '-'} | "
                  f"quotes: {', '.join('E' + str(e) for e in sc.get('excerpt_ids') or []) or '-'}", ""]
        if sc.get("music"):
            lines += ["### MUSIC", render_music(sc["music"]), ""]
        if sc.get("owlbert"):
            lines += ["### OWLBERT", render_owlbert(sc["owlbert"]), ""]
        lines += ["---", ""]
    return "\n".join(lines)


SINGLE_QUOTED = re.compile(r"(?<![\w'’])['‘](?!\d)([^\"“”\n]{1,300}?)['’](?!\w)")


def quotes_in(narration: str) -> list[str]:
    """Text inside double quotes (straight or curly), and inside single quotes when it's 3 words or more
    (so "didn't" and "'90s" aren't quotes, but 'the worst time for humanity' is)."""
    found = [q.strip() for q in re.findall(r"[\"“]([^\"”]{12,})[\"”]", narration)]
    found += [q.strip() for q in SINGLE_QUOTED.findall(narration) if len(q.split()) >= 3]
    return [q.rstrip(" .,;:!?") for q in found]
