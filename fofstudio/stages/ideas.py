"""Scan data for stories (Dave, 2026-10-30): every video the ticked research could make, with its length.

"When all the research is selected and copied to stories have a button at the top say scan data for stories
and have the local AI go over all the data and list out all the short stories, long stories, and info clips
that can be made from the data and list out how long each video would be. Then the user can select the one
they want to make and they can choose the type of story or book or short info clip to have made and the
type of writer."

The local AI reads the ticked evidence and lists ideas in three kinds:
  info clip     one striking fact or one claim taken apart, 30-90 seconds (a YouTube Short)
  short story   one claim or one thread told properly, about 2-10 minutes
  long story    several claims or the whole saga, about 10-40 minutes (a book-sized one can also be a book)
Each idea names the claims and evidence it uses (only IDs that exist), so the stories written from it stay
on that evidence. The length is the program's honest arithmetic from that material (the same formula as the
Script page's length scan), kept inside the kind's range; the AI's guess is only used to split ties. An idea
whose material doesn't fill its kind moves to the kind it really fits (never padded).
Nothing is written yet: you pick an idea, how to make it (2 stories, 2 info clips or 1 book) and the writer.
"""

from __future__ import annotations

from typing import Any

from ..episode import Episode
from ..llm import Ollama
from ..util import StageError, read_json, utc_now, write_json
from .base import Context

KINDS = {"clip": "Info clip", "short": "Short story", "long": "Long story"}
RANGES = {"clip": (30, 90), "short": (120, 600), "long": (600, 2400)}
MAKE = {"story": "2 stories", "clip": "2 info clips", "book": "1 book"}

IDEA_SCHEMA = {"type": "object", "properties": {"ideas": {"type": "array", "minItems": 1, "maxItems": 24, "items": {
    "type": "object", "properties": {
        "kind": {"type": "string", "enum": list(KINDS)},
        "title": {"type": "string"},
        "pitch": {"type": "string"},
        "claim_ids": {"type": "array", "items": {"type": "string"}},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "minutes_guess": {"type": "number", "minimum": 0.25, "maximum": 60}},
    "required": ["kind", "title", "pitch", "claim_ids", "evidence_ids", "minutes_guess"]}}},
    "required": ["ideas"]}

RULES = """You are the story editor for "Followers or Facts", a fact-check channel. Read ALL the research below
and list every video it could honestly make, in three kinds:
  clip  = an INFO CLIP: one striking, sourced fact or one claim taken apart in 30-90 seconds;
  short = a SHORT STORY: one claim, one person or one thread told properly (a few minutes);
  long  = a LONG STORY: several claims or the whole saga (ten minutes or more).
List 4-8 info clips, 3-6 short stories and 1-3 long stories when the material allows (fewer if it doesn't;
never invent material to reach a number). Each idea is a different angle or a different part of the record:
no two ideas the same. title: a working title (no clickbait the video can't back up). pitch: one or two
sentences on what the viewer learns. claim_ids and evidence_ids: ONLY IDs from the list that this idea uses.
minutes_guess: how long it needs. Never mock believers; aim at the people who sold the lie; careful topics
(victims) stay respectful: courts and documents only."""


def _packet(ep: Episode) -> dict[str, Any]:
    from .research import selected
    return selected(read_json(ep.path("research.json")) or {})


def seconds_for(idea: dict[str, Any], packet: dict[str, Any]) -> int:
    """The honest length of an idea from its own material: the length scan's formula on its claims and
    evidence (fixed parts, each claim with its primary sources, each quote, one trick)."""
    from .lengthscan import SOURCE_WEIGHTS
    ev = {e["id"]: e for e in packet.get("evidence", [])}
    mine = [ev[i] for i in idea["evidence_ids"] if i in ev]
    claims = idea["claim_ids"] or sorted({e["claim_id"] for e in mine})
    if idea["kind"] == "clip":
        quotes = sum(1 for e in mine if e.get("kind") == "quote")
        return int(min(90, max(30, 20 + 15 * len(claims[:2]) + 10 * min(3, quotes) + 5 * min(4, len(mine)))))
    fixed = 25 + 8 + 30 + 25
    total = fixed + 45 + 60   # context and one trick
    for c in claims:
        prim = sum(1 for e in mine if e["claim_id"] == c and (e.get("type") in ("court", "government", "primary",
                                                                                 "document", "court_record")))
        w = sum(SOURCE_WEIGHTS[i] if i < len(SOURCE_WEIGHTS) else 0.15 for i in range(prim))
        total += 75 + 30 * w
    total += 12 * sum(1 for e in mine if e.get("kind") == "quote")
    return int(round(total * 1.10 / 30) * 30)


def _fit(idea: dict[str, Any], seconds: int) -> tuple[str, int]:
    """Keep the length honest: a story whose material only fills a few minutes is a short story, and a
    'short' with a lot of material is a long one. Info clips stay clips (one fact, cut tight)."""
    kind = idea["kind"]
    if kind != "clip":
        kind = "long" if seconds > RANGES["short"][1] else "short"
    lo, hi = RANGES[kind]
    return kind, max(lo, min(hi, seconds))


def run(ctx: Context) -> None:
    ep = ctx.episode
    packet = _packet(ep)
    if not packet.get("evidence"):
        raise StageError("Nothing is ticked on the Research page yet. Tick the research, approve it, then scan.")
    from .stories import evidence_for_prompt
    ctx.progress("The local AI is reading all the ticked research for story ideas", 5)
    ans = Ollama(job="stories").chat_json([
        {"role": "system", "content": RULES},
        {"role": "user", "content": f"Research:\n{evidence_for_prompt(ep)}\n\nList the ideas."}],
        IDEA_SCHEMA, temperature=0.5, on_text=ctx.writing("Listing the story ideas", 5, 90, 900))
    claim_ids = {c["claim_id"] for c in packet.get("claims", [])}
    ev_ids = {e["id"] for e in packet.get("evidence", [])}
    ideas, seen = [], set()
    for raw in ans.get("ideas") or []:
        title = " ".join(str(raw.get("title") or "").split())[:120]
        if not title or title.lower() in seen:
            continue
        idea = {"kind": raw.get("kind") if raw.get("kind") in KINDS else "short", "title": title,
                "pitch": " ".join(str(raw.get("pitch") or "").split())[:400],
                "claim_ids": [c for c in raw.get("claim_ids") or [] if c in claim_ids],
                "evidence_ids": [e for e in raw.get("evidence_ids") or [] if e in ev_ids]}
        if not idea["claim_ids"] and idea["evidence_ids"]:
            by = {e["id"]: e["claim_id"] for e in packet["evidence"]}
            idea["claim_ids"] = sorted({by[e] for e in idea["evidence_ids"]})
        if not idea["claim_ids"]:
            continue                      # an idea that uses nothing from the research isn't an idea
        if not idea["evidence_ids"]:
            idea["evidence_ids"] = [e["id"] for e in packet["evidence"] if e["claim_id"] in idea["claim_ids"]]
        idea["kind"], idea["seconds"] = _fit(idea, seconds_for(idea, packet))
        seen.add(title.lower())
        ideas.append(idea)
    if not ideas:
        raise StageError("The local AI didn't list any ideas that use the ticked research. Try the scan again.")
    order = {"clip": 0, "short": 1, "long": 2}
    ideas.sort(key=lambda i: (order[i["kind"]], i["seconds"]))
    for n, idea in enumerate(ideas, 1):
        idea["id"] = f"I{n:02d}"
    write_json(ep.path("ideas.json"), {"ideas": ideas, "made_at": utc_now(),
                                       "evidence_count": len(ev_ids)})
    counts = {k: sum(1 for i in ideas if i["kind"] == k) for k in KINDS}
    ctx.progress(f"Found {counts['clip']} info clip(s), {counts['short']} short story(ies) and {counts['long']} long "
                 "story(ies). Pick one, choose how to make it and the writer, then Create.", 100)


def load(ep: Episode) -> list[dict[str, Any]]:
    return (read_json(ep.path("ideas.json")) or {}).get("ideas", [])


def length_text(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds < 3600 else f"{seconds // 3600}h {seconds // 60 % 60:02d}m"


def focus_note(idea: dict[str, Any]) -> str:
    """What the story writer is told when a story is made from a scanned idea."""
    return (f"\n\nMake it about THIS idea from the story scan, and only it: \"{idea['title']}\": {idea['pitch']} "
            f"It uses claims {', '.join(idea['claim_ids'])} and evidence {', '.join(idea['evidence_ids'][:40])}; "
            "lead with that evidence and leave the rest of the research out unless a beat truly needs it.")
