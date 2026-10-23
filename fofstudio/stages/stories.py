"""Stories: three different ways to tell the tale and take the lie apart.

Each option has a title, a one-line pitch, the angle it takes, and a beat-by-beat
outline that names the evidence each beat leans on. You pick one; you can ask for
any option to be rewritten with your notes. The chosen story goes to the Script stage.
"""

from __future__ import annotations

import json
from typing import Any

from ..episode import Episode
from ..llm import Ollama
from ..util import StageError, read_json, utc_now, write_json
from .base import BLOCK, OK, WARN, Check, Context

BEAT_SCHEMA = {
    "type": "object",
    "properties": {
        "role": {"type": "string", "enum": ["intro", "claim", "record", "benefit", "harm", "verdict"]},
        "beat": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["role", "beat", "evidence_ids"],
}
STORY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "logline": {"type": "string"},
        "angle": {"type": "string"},
        "opening_hook": {"type": "string"},
        "beats": {"type": "array", "items": BEAT_SCHEMA},
        "owl_moments": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "logline", "angle", "opening_hook", "beats", "owl_moments"],
}
THREE_SCHEMA = {"type": "object", "properties": {"stories": {"type": "array", "items": STORY_SCHEMA}},
                "required": ["stories"]}

ANGLES = [
    "Follow the money: tell it through who sold the fear and what they earned.",
    "Then and now: walk the timeline from the first rumor to what the record shows today.",
    "The people it hurt: tell it through the real-world harm, respectfully, courts and documents only.",
]

RULES = """You plan stories for "Followers or Facts", a calm, kind fact-check channel narrated by
Professor Owlbert McFinnegan, a warm, curious cartoon owl professor.
Rules: use only facts in the evidence list; every beat names the evidence IDs it relies on
(E-numbers and S-IDs from the list, nothing else); never mock the people who believed it;
aim criticism at the people who sold it; respect every careful-topic rule; plain words.
Every story must have beats for: claim (what was claimed), record (what the record says),
benefit (who benefited), harm (what it did to people), and end with a verdict.
owl_moments: 2-4 places where Owlbert appears on camera (e.g. "opens at his desk").
"""


def evidence_for_prompt(ep: Episode) -> str:
    packet = read_json(ep.path("research.json")) or {}
    items = []
    for c in packet.get("claims", []):
        items.append({"claim_id": c["claim_id"], "claim": c["short_title"], "verdict": c["falsity_status"],
                      "summary": c.get("claim_summary"), "harm": c.get("harm_summary"),
                      "who_benefited": c.get("who_benefited")})
    evidence = [{"id": e["id"], "type": e.get("kind"), "title": e.get("title"),
                 "date": e.get("date"), "quote": e.get("quote"), "supports": e.get("supports")}
                for e in packet.get("evidence", [])]
    return json.dumps({"subject": packet.get("subject"), "claims": items, "evidence": evidence,
                       "careful_rules": [f"{r['rule']}: {r.get('note') or ''}"
                                         for r in packet.get("restrictions", [])]},
                      ensure_ascii=False, indent=1)


def _valid_ids(ep: Episode) -> set[str]:
    packet = read_json(ep.path("research.json")) or {}
    ids = {e["id"] for e in packet.get("evidence", [])}
    for c in packet.get("claims", []):
        ids |= {s["source_id"] for s in c.get("sources", []) if s.get("is_primary")}
    return ids


def _clean(story: dict[str, Any], valid: set[str]) -> dict[str, Any]:
    for b in story.get("beats", []):
        b["evidence_ids"] = [e for e in b.get("evidence_ids", []) if e in valid]
    return story


def run(ctx: Context) -> None:
    ep = ctx.episode
    if not ep.path("research.json").exists():
        raise StageError("Approve Research first.")
    data = read_json(ep.path("stories.json"), {}) or {}
    valid = _valid_ids(ep)
    llm = Ollama()
    rewrite = ctx.options.get("rewrite")  # {"index": 1, "notes": "..."}
    if rewrite:
        i = int(rewrite["index"])
        old = data["options"][i]
        ctx.progress(f"Rewriting story {i + 1} with your notes", 20)
        new = llm.chat_json([
            {"role": "system", "content": RULES},
            {"role": "user", "content": f"Evidence:\n{evidence_for_prompt(ep)}\n\nHere is a story plan:\n"
                                        f"{json.dumps(old, ensure_ascii=False)}\n\nRewrite it with these notes "
                                        f"from the producer: {rewrite['notes']}"},
        ], STORY_SCHEMA, temperature=0.6)
        new = _clean(new, valid)
        new["revision"] = old.get("revision", 1) + 1
        new["notes_applied"] = rewrite["notes"]
        data["options"][i] = new
        data.pop("chosen", None)
    else:
        options = []
        for n, angle in enumerate(ANGLES):
            ctx.check_cancel()
            ctx.progress(f"Writing story option {n + 1} of 3: {angle.split(':')[0]}", 10 + n * 30)
            story = llm.chat_json([
                {"role": "system", "content": RULES},
                {"role": "user", "content": f"Evidence:\n{evidence_for_prompt(ep)}\n\nPlan ONE story with this "
                                            f"angle: {angle}\n6 to 10 beats."},
            ], STORY_SCHEMA, temperature=0.8)
            story = _clean(story, valid)
            story["angle_hint"] = angle
            story["revision"] = 1
            options.append(story)
        data = {"options": options, "made_at": utc_now()}
    write_json(ep.path("stories.json"), data)
    ctx.progress("Stories ready. Pick one.", 100)


def choose(ep: Episode, index: int) -> None:
    data = read_json(ep.path("stories.json"))
    if not data or not 0 <= index < len(data["options"]):
        raise StageError("No such story option.")
    data["chosen"] = index
    write_json(ep.path("stories.json"), data)


def chosen(ep: Episode) -> dict[str, Any] | None:
    data = read_json(ep.path("stories.json")) or {}
    if data.get("chosen") is None:
        return None
    return data["options"][data["chosen"]]


def check(ep: Episode) -> list[Check]:
    data = read_json(ep.path("stories.json"))
    if not data:
        return [Check(BLOCK, "No stories yet. Press Create stories.")]
    if data.get("chosen") is None:
        return [Check(BLOCK, "Pick one of the three stories.")]
    story = data["options"][data["chosen"]]
    out = []
    roles = {b["role"] for b in story["beats"]}
    for need in ("claim", "record", "benefit", "harm"):
        if need not in roles:
            out.append(Check(BLOCK, f"The chosen story has no '{need}' beat. Ask for a rewrite."))
    bare = [b["beat"][:50] for b in story["beats"] if b["role"] in ("record", "claim") and not b["evidence_ids"]]
    if bare:
        out.append(Check(WARN, f"{len(bare)} fact beat(s) don't name evidence yet: {bare[0]}..."))
    out.append(Check(OK, f"Chosen: \"{story['title']}\" ({len(story['beats'])} beats)."))
    return out
