"""Channel memory: what earlier videos on the same subject already said, so a new one doesn't open, end or
lead the same way (the "broken record" across a series).

Kept in <data>/channel-memory.json, one entry per episode: its arc and claims, how it opened and ended, the
story's hook, the quotes it used and the facts it led with. Written when a script is drafted; read by the
story writer and the script writer for episodes that share a claim or an arc.
"""

from __future__ import annotations

from typing import Any

from .config import Paths
from .util import read_json, utc_now, write_json


def _path():
    return Paths().root / "channel-memory.json"


def load() -> dict[str, Any]:
    return read_json(_path(), {}) or {}


def record(ep, scenes: list[dict[str, Any]], story: dict[str, Any] | None, title: str) -> None:
    from .repeats import key_sentences, opening_and_ending
    data = load()
    opening, ending = opening_and_ending(scenes)
    facts = []
    for sc in scenes:
        if sc.get("role") in ("claim", "record", "benefit", "harm"):
            facts += key_sentences(sc.get("narration", ""), 1)
    data[ep.project_id] = {
        "title": title, "arc": (ep.info or {}).get("arc_id"), "claims": list(ep.claim_ids),
        "opening": opening, "ending": ending, "hook": (story or {}).get("opening_hook", ""),
        "story_title": (story or {}).get("title", ""),
        "quotes": sorted({int(e) for sc in scenes for e in sc.get("excerpt_ids", []) if str(e).isdigit()}),
        "facts": facts[:12], "made_at": utc_now()}
    write_json(_path(), data)


def related(ep) -> list[dict[str, Any]]:
    """Other episodes that share a claim or the arc with this one, newest first."""
    mine = set(ep.claim_ids)
    arc = (ep.info or {}).get("arc_id")
    out = []
    for pid, e in load().items():
        if pid == ep.project_id:
            continue
        if (arc and e.get("arc") == arc) or mine & set(e.get("claims", [])):
            out.append({"project_id": pid, **e})
    return sorted(out, key=lambda e: e.get("made_at", ""), reverse=True)[:6]


def for_prompt(ep, part: str = "all") -> str:
    """Text for the writers: what not to reuse from earlier videos on this subject."""
    rel = related(ep)
    if not rel:
        return ""
    lines = ["Earlier videos on this channel about the same subject already did these; do something different "
             "(a different opening, a different ending, lead with different evidence, new details):"]
    for e in rel:
        bits = [f"\"{e.get('title', '')}\""]
        if part in ("all", "story") and e.get("hook"):
            bits.append(f"hook: {e['hook'][:160]}")
        if part in ("all", "opening") and e.get("opening"):
            bits.append(f"opened: {e['opening'][:200]}")
        if part in ("all", "ending") and e.get("ending"):
            bits.append(f"ended: {e['ending'][:200]}")
        if part == "all" and e.get("facts"):
            bits.append("led with: " + " | ".join(f[:120] for f in e["facts"][:4]))
        lines.append("- " + "; ".join(bits))
    return "\n".join(lines)


def quotes_used_elsewhere(ep) -> set[int]:
    return {q for e in related(ep) for q in e.get("quotes", [])}
