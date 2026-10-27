"""The film treatment: the script writer works as a cinematic story architect, not a report writer.

Dave's brief (2026-10-27): take the research and find the story hidden in it - the characters, conflicts,
mysteries, goals, obstacles and emotional stakes - and build a narrative arc (hook, setup, rising tension,
discovery, climax, resolution, future implications) like a documentary or limited series, in the chosen
director's style, without ever inventing a fact. Output: film title, logline, opening scene, three-act
structure, key characters, major revelations, emotional arc, and then the final narrative (the scenes).

So before any narration is written, the planner makes a treatment (treatment.json / treatment.md, shown on the
Script page). Every scene then gets its place in the arc, its act's emotional note, the characters, and the
revelation it must land, so the narration tells a story instead of summarising research. The editorial rules
still win: characters are only real people and groups from the research (nobody invented), revelations name
the evidence that proves them, and the director is described by traits only, never by name.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

from ..util import write_json, write_text

ARC = [
    ("hook", "Hook: a true, surprising moment or question that grabs the viewer before any explaining"),
    ("setup", "Setup: the world, the people, what they wanted and what was at stake"),
    ("rising", "Rising tension: the claim spreads, obstacles pile up, the stakes get higher"),
    ("discovery", "Discovery: the documents and the record start to show what really happened"),
    ("climax", "Climax: the turning point, the biggest revelation, the moment the lie breaks"),
    ("resolution", "Resolution: what it cost, who paid, what the verdict is"),
    ("implications", "Future implications: what it means now, the open questions, the thought to leave with"),
]
ARC_KEYS = [k for k, _ in ARC]
ARC_SHARE = {"hook": 7, "setup": 14, "rising": 21, "discovery": 21, "climax": 12, "resolution": 15, "implications": 10}
ACT_OF = {"hook": 1, "setup": 1, "rising": 2, "discovery": 2, "climax": 2, "resolution": 3, "implications": 3}

ARCHITECT = """You are not a report writer. You are a cinematic story architect.
Your job is to take the factual research and turn it into a compelling narrative that feels like a film,
in the directing style described below.
1. Never simply summarize research. Find the story in it.
2. Identify the characters, conflicts, mysteries, goals, obstacles and emotional stakes hidden in the research.
3. Build the arc: hook, setup, rising tension, discovery, climax, resolution, future implications.
4. Preserve factual accuracy. Do not invent facts, people, dialogue, thoughts or events. Characters are only
   real people and groups named in the research (or "the believers", "the viewers" as groups); a character's
   wants and fears must come from what the record shows they said or did.
5. Use storytelling, not academic language. No "according to the research", "in summary", "this report".
6. Explain complex ideas through human experiences, everyday analogies and visual descriptions.
7. Write as if pitching a documentary, feature film or limited series.
8. Make the audience care about the outcome: real people were affected.
9. Highlight turning points, surprises and unanswered questions.
10. End with a memorable conclusion that leaves the audience thinking.
The facts are fixed; the storytelling is yours. Never mock the people who believed it; aim at the sellers."""


def schema(ids: dict[str, list]) -> dict[str, Any]:
    ev = sorted(set(ids.get("source_ids", [])) | {f"E{e}" for e in ids.get("excerpt_ids", [])}) or ["none"]
    return {"type": "object", "properties": {
        "film_title": {"type": "string"},
        "logline": {"type": "string"},
        "opening_scene": {"type": "string"},
        "acts": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "object", "properties": {
            "act": {"type": "integer", "minimum": 1, "maximum": 3},
            "title": {"type": "string"}, "what_happens": {"type": "string"},
            "emotion": {"type": "string"}, "turning_point": {"type": "string"}},
            "required": ["act", "title", "what_happens", "emotion", "turning_point"]}},
        "key_characters": {"type": "array", "maxItems": 5, "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "role": {"type": "string"}, "wants": {"type": "string"},
            "obstacle": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string", "enum": ev}}},
            "required": ["name", "role", "wants", "obstacle", "evidence"]}},
        "revelations": {"type": "array", "maxItems": 6, "items": {"type": "object", "properties": {
            "reveal": {"type": "string"}, "why_it_matters": {"type": "string"},
            "arc": {"type": "string", "enum": ARC_KEYS},
            "evidence": {"type": "array", "minItems": 1, "items": {"type": "string", "enum": ev}}},
            "required": ["reveal", "why_it_matters", "arc", "evidence"]}},
        "emotional_arc": {"type": "string"},
        "unanswered_questions": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
        "closing_thought": {"type": "string"}},
        "required": ["film_title", "logline", "opening_scene", "acts", "key_characters", "revelations",
                     "emotional_arc", "unanswered_questions", "closing_thought"]}


def known_names(packet: dict[str, Any]) -> set[str]:
    names = set()
    for c in packet.get("claims", []):
        names |= {p["name"].lower() for p in c.get("people", [])} | {o["name"].lower() for o in c.get("orgs", [])}
    return names


def real_character(name: str, names: set[str]) -> bool:
    """A character must be a real person or group from the research, or a plain group ('the believers')."""
    n = (name or "").strip()
    if not n:
        return False
    low = n.lower()
    if low in names or any(low in k or k in low for k in names if len(k) > 3):
        return True
    proper = re.findall(r"\b[A-Z][a-z]+", n[1:]) if n else []
    return not proper          # no proper names = a generic group, e.g. "the believers", "Radio listeners"


def tidy(raw: dict[str, Any], packet: dict[str, Any], ids: dict[str, list]) -> dict[str, Any]:
    ok_ev = set(ids.get("source_ids", [])) | {f"E{e}" for e in ids.get("excerpt_ids", [])}
    names = known_names(packet)
    chars, dropped = [], []
    for c in raw.get("key_characters", []):
        if real_character(c.get("name", ""), names):
            chars.append({**c, "evidence": [e for e in c.get("evidence", []) if e in ok_ev]})
        else:
            dropped.append(c.get("name", ""))
    revs = []
    for r in raw.get("revelations", []):
        ev = [e for e in r.get("evidence", []) if e in ok_ev]
        if ev and (r.get("reveal") or "").strip():
            revs.append({**r, "evidence": ev, "arc": r.get("arc") if r.get("arc") in ARC_KEYS else "discovery"})
    acts = sorted([a for a in raw.get("acts", []) if a.get("act") in (1, 2, 3)], key=lambda a: a["act"])
    return {"film_title": (raw.get("film_title") or "").strip(), "logline": (raw.get("logline") or "").strip(),
            "opening_scene": (raw.get("opening_scene") or "").strip(), "acts": acts[:3], "key_characters": chars[:5],
            "revelations": revs[:6], "emotional_arc": (raw.get("emotional_arc") or "").strip(),
            "unanswered_questions": [q for q in raw.get("unanswered_questions", []) if q.strip()][:4],
            "closing_thought": (raw.get("closing_thought") or "").strip(), "dropped_characters": dropped}


def assign_arc(planned: list[dict[str, Any]]) -> None:
    """Give every planned scene its place in the arc, in order, by its position in the video."""
    n = len(planned)
    bounds, total = [], 0
    for k in ARC_KEYS:
        total += ARC_SHARE[k]
        bounds.append((total, k))
    for i, sc in enumerate(planned):
        pos = (i + 0.5) / max(1, n) * 100
        sc["arc"] = next(k for b, k in bounds if pos <= b) if pos <= 100 else "implications"
    if n:
        planned[0]["arc"] = "hook"
        planned[-1]["arc"] = "implications" if n > 2 else planned[-1]["arc"]


def place_revelations(treatment: dict[str, Any], planned: list[dict[str, Any]]) -> None:
    """Each revelation goes to the scene that holds its evidence (nearest its arc stage), once."""
    for r in treatment.get("revelations", []):
        wanted = set(r["evidence"])
        best, score = None, -1.0
        for i, sc in enumerate(planned):
            have = set(sc.get("source_ids", []) or []) | {f"E{e}" for e in sc.get("excerpt_ids", []) or []}
            s = len(wanted & have) * 3 + (2 if sc.get("arc") == r["arc"] else 0) - (5 if sc.get("revelation") else 0)
            if s > score:
                best, score = i, s
        if best is not None:
            planned[best]["revelation"] = r["reveal"]


def scene_brief(t: dict[str, Any], sc: dict[str, Any], n: int, total: int) -> str:
    """What the scene writer needs from the treatment for this one scene."""
    if not t:
        return ""
    arc = sc.get("arc") or "discovery"
    act = next((a for a in t.get("acts", []) if a.get("act") == ACT_OF.get(arc, 2)), {})
    lines = [f"THE FILM: \"{t.get('film_title', '')}\" - {t.get('logline', '')}",
             f"This scene's place in the arc: {dict(ARC)[arc]}"]
    if act:
        lines.append(f"Act {act['act']} ({act.get('title', '')}): {act.get('what_happens', '')} Feeling: "
                     f"{act.get('emotion', '')}. Turning point: {act.get('turning_point', '')}")
    if t.get("key_characters"):
        lines.append("Characters (real, from the research): " + "; ".join(
            f"{c['name']} ({c.get('role', '')}; wants {c.get('wants', '')}; obstacle: {c.get('obstacle', '')})"
            for c in t["key_characters"]))
    if n == 1 and t.get("opening_scene"):
        lines.append(f"Open the film like this (using only this scene's facts): {t['opening_scene']}")
    if sc.get("revelation"):
        lines.append(f"The revelation this scene must land (build to it; make it hit): {sc['revelation']}")
    if arc == "implications":
        if t.get("unanswered_questions"):
            lines.append("Questions still open: " + " | ".join(t["unanswered_questions"]))
        if n == total and t.get("closing_thought"):
            lines.append(f"End on this thought, so it stays with the viewer: {t['closing_thought']}")
    if t.get("emotional_arc"):
        lines.append(f"Emotional arc of the whole film: {t['emotional_arc']}")
    return "\n".join(lines)


def save(ep, t: dict[str, Any]) -> None:
    write_json(ep.path("treatment.json"), t)
    write_text(ep.path("treatment.md"), to_markdown(t))


def load(ep) -> dict[str, Any]:
    from ..util import read_json
    return read_json(ep.path("treatment.json"), {}) or {}


def to_markdown(t: dict[str, Any]) -> str:
    out = [f"# {t.get('film_title', '')}", "", f"**Logline:** {t.get('logline', '')}", "",
           "## Opening scene", t.get("opening_scene", ""), "", "## Three-act structure"]
    for a in t.get("acts", []):
        out += [f"**Act {a['act']}: {a.get('title', '')}** - {a.get('what_happens', '')} "
                f"(feeling: {a.get('emotion', '')}; turning point: {a.get('turning_point', '')})"]
    out += ["", "## Key characters"] + [f"- **{c['name']}** ({c.get('role', '')}): wants {c.get('wants', '')}; "
                                        f"obstacle: {c.get('obstacle', '')} [{', '.join(c.get('evidence', []))}]"
                                        for c in t.get("key_characters", [])]
    out += ["", "## Major revelations"] + [f"- {r['reveal']} ({r.get('why_it_matters', '')}) [{', '.join(r['evidence'])}]"
                                           for r in t.get("revelations", [])]
    out += ["", "## Emotional arc", t.get("emotional_arc", ""), "", "## Open questions"]
    out += [f"- {q}" for q in t.get("unanswered_questions", [])]
    out += ["", "## Closing thought", t.get("closing_thought", ""), "",
            "The final narrative is the script (script.md)."]
    return "\n".join(out) + "\n"


def to_html(t: dict[str, Any]) -> str:
    if not t:
        return ""
    e = html.escape
    acts = "".join(f"<li><b>Act {a['act']}: {e(a.get('title', ''))}</b> - {e(a.get('what_happens', ''))} "
                   f"<i>({e(a.get('emotion', ''))}; turning point: {e(a.get('turning_point', ''))})</i></li>"
                   for a in t.get("acts", []))
    chars = "".join(f"<li><b>{e(c['name'])}</b> ({e(c.get('role', ''))}): wants {e(c.get('wants', ''))}; obstacle: "
                    f"{e(c.get('obstacle', ''))}</li>" for c in t.get("key_characters", []))
    revs = "".join(f"<li>{e(r['reveal'])} <span style='color:#888'>[{e(', '.join(r['evidence']))}]</span></li>"
                   for r in t.get("revelations", []))
    qs = "".join(f"<li>{e(q)}</li>" for q in t.get("unanswered_questions", []))
    return (f"<h2>{e(t.get('film_title', ''))}</h2><p><i>{e(t.get('logline', ''))}</i></p>"
            f"<p><b>Opening scene:</b> {e(t.get('opening_scene', ''))}</p><p><b>Three acts</b></p><ol>{acts}</ol>"
            f"<p><b>Key characters</b></p><ul>{chars}</ul><p><b>Major revelations</b></p><ul>{revs}</ul>"
            f"<p><b>Emotional arc:</b> {e(t.get('emotional_arc', ''))}</p>"
            + (f"<p><b>Open questions</b></p><ul>{qs}</ul>" if qs else "")
            + f"<p><b>Closing thought:</b> {e(t.get('closing_thought', ''))}</p>")


def brief_for_outline(t: dict[str, Any]) -> str:
    return "The film treatment to follow:\n" + json.dumps({k: t.get(k) for k in (
        "film_title", "logline", "opening_scene", "acts", "key_characters", "revelations", "emotional_arc")},
        ensure_ascii=False, indent=1)
