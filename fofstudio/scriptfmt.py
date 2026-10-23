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

Older truth-vlog scripts without the role or SOURCES line still parse.
"""

from __future__ import annotations

import re
from typing import Any

# tell = Owlbert names the trick; toolkit = the question to ask next time
ROLES = ("intro", "claim", "record", "benefit", "harm", "tell", "toolkit", "verdict", "outro", "credits")
SECTIONS = ("VISUAL", "NARRATION", "ON_SCREEN_TEXT", "SOURCES", "CLIP", "NOTES")


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
                  f"quotes: {', '.join('E' + str(e) for e in sc.get('excerpt_ids') or []) or '-'}",
                  "", "---", ""]
    return "\n".join(lines)


def quotes_in(narration: str) -> list[str]:
    """Text inside double quotes in the narration (straight or curly)."""
    found = re.findall(r"[\"“]([^\"”]{12,})[\"”]", narration)
    return [q.strip() for q in found]
