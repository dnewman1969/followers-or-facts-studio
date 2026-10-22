"""Stage 2 - Script.

The local AI drafts the script from the research packet only. Every scene
carries the claim IDs and source IDs it relies on, and quotes may only come
from verified excerpts. You can edit script.md by hand and press Re-check.
"""

from __future__ import annotations

import json
from typing import Any

from .. import db
from ..config import settings
from ..episode import Episode
from ..llm import Ollama
from ..scriptfmt import ROLES, parse, quotes_in, render
from ..util import StageError, normalize_for_match, read_json, reading_grade, write_text
from .base import BLOCK, OK, WARN, Check, Context

WORDS_PER_MINUTE = 150

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "role": {"type": "string", "enum": list(ROLES[:-1])},
                    "visual": {"type": "string"},
                    "narration": {"type": "string"},
                    "on_screen_text": {"type": "string"},
                    "claim_ids": {"type": "array", "items": {"type": "string"}},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                    "excerpt_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["role", "visual", "narration", "on_screen_text",
                             "claim_ids", "source_ids", "excerpt_ids"],
            },
        },
    },
    "required": ["title", "scenes"],
}

VOICE_RULES = """You write narration for "Followers or Facts", a calm, kind fact-check channel.
The narrator is Professor Owlbert McFinnegan, a warm, curious owl professor.

Hard rules (breaking any of them makes the script unusable):
1. Use ONLY facts from the research packet. Never invent a date, number, name, quote or source.
2. Every scene that states a fact lists the claim_ids and source_ids it relies on. Use only
   source IDs listed for that claim. Never use a Knowledge Fight (kf_index) source as evidence.
3. Direct quotes: only copy text from a verified quote (by its excerpt_id) word for word,
   inside double quotes, and list that excerpt_id. Otherwise paraphrase with no quote marks.
4. Plain 6th-grade English: short sentences, everyday words, explain any jargon.
5. Never mock the people who believed the claim. Aim criticism at the people who sold it.
6. If a claim's verdict is "unverified" or "contested", say so plainly. Don't call it false.
7. Careful topics: follow every restriction listed in the packet (for victims: courts and
   documents only, no names of private people, no description of the violence).
8. The video must answer four questions, each in at least one scene with that role:
   claim (what was claimed), record (what the record says), benefit (who benefited),
   harm (what it did to people). Start with an "intro" scene and end with a "verdict" scene.
9. VISUAL describes a picture for an illustrator: scrapbook documentary style, objects,
   places, documents, moods. No real people's faces, no readable text, no logos.
10. ON_SCREEN_TEXT is at most 8 words (a date, a place, a short label) or empty."""


def _packet_for_prompt(packet: dict[str, Any]) -> str:
    slim = {"arc": (packet.get("arc") or {}).get("title"), "restrictions": [
        f"{r['rule']} ({r['subject_id']}): {r.get('note') or ''}" for r in packet["restrictions"]],
        "claims": []}
    for c in packet["claims"]:
        slim["claims"].append({
            "claim_id": c["claim_id"], "title": c["short_title"], "summary": c.get("claim_summary"),
            "first_known_year": c.get("first_known_year"), "verdict": c["falsity_status"],
            "harm": c.get("harm_summary"), "who_benefited": c.get("who_benefited"),
            "society_effect": c.get("society_effect"),
            "people": [f"{p['name']} ({p['link_role']})" for p in c["people"]],
            "sources": [{"source_id": s["source_id"], "type": s["source_type"], "title": s["title"],
                         "publisher": s.get("publisher"), "date": s.get("date")}
                        for s in c["sources"] if s["is_primary"]],
            "verified_quotes": [{"excerpt_id": e["excerpt_id"], "source_id": e["source_id"],
                                 "text": e["text"]} for e in c["excerpts"]],
        })
    return json.dumps(slim, ensure_ascii=False, indent=1)


def run(ctx: Context) -> None:
    ep = ctx.episode
    packet = read_json(ep.path("research.json"))
    if not packet:
        raise StageError("Run and approve the Research stage first.")
    minutes = float(ctx.options.get("minutes", 8))
    words = int(minutes * WORDS_PER_MINUTE)
    ctx.progress(f"Writing a ~{minutes:g} minute script with {settings()['ollama']['writer_model']}")
    answer = Ollama().chat_json([
        {"role": "system", "content": VOICE_RULES},
        {"role": "user", "content": (
            f"Episode working title: {ep.title}\n"
            f"Target length: about {words} words of narration in 6 to 12 scenes.\n"
            + (f"Extra direction from the producer: {ctx.options['direction']}\n"
               if ctx.options.get("direction") else "")
            + f"\nResearch packet:\n{_packet_for_prompt(packet)}")},
    ], SCRIPT_SCHEMA, temperature=0.6)
    scenes = answer.get("scenes") or []
    if len(scenes) < 3:
        raise StageError("The draft came back with fewer than 3 scenes. Run the stage again.")
    for n, sc in enumerate(scenes, 1):
        sc["scene_id"] = f"SCENE_{n:03d}"
        sc["est_seconds"] = round(len(sc.get("narration", "").split()) / WORDS_PER_MINUTE * 60)
    header = {"Episode": ep.project_id, "Arc": (packet.get("arc") or {}).get("arc_id", "-"),
              "Drafted by": settings()["ollama"]["writer_model"]}
    write_text(ep.path("script.md"), render(answer.get("title") or ep.title, scenes, header))
    ctx.log(f"Draft written: {len(scenes)} scenes. Read and edit script.md, then Re-check.")


def check(ep: Episode) -> list[Check]:
    path = ep.path("script.md")
    if not path.exists():
        return [Check(BLOCK, "No script yet. Run this stage (or write script.md yourself).")]
    packet = read_json(ep.path("research.json")) or {"claims": []}
    script = parse(path.read_text(encoding="utf-8"))
    scenes = script["scenes"]
    out: list[Check] = []
    if not scenes:
        return [Check(BLOCK, "script.md has no '## SCENE_###' headings.")]

    claim_sources = {c["claim_id"]: {s["source_id"] for s in c["sources"] if s["is_primary"]}
                     for c in packet["claims"]}
    all_primary = set().union(*claim_sources.values()) if claim_sources else set()
    excerpts = {str(e["excerpt_id"]): e for c in packet["claims"] for e in c["excerpts"]}
    known_sources = {r["source_id"] for r in db.rows("SELECT source_id FROM source")}

    for sc in scenes:
        sid = sc["scene_id"]
        for cid in sc["claim_ids"]:
            if cid not in claim_sources:
                out.append(Check(BLOCK, f"{sid}: claim {cid} is not in this episode's research packet."))
        for src in sc["source_ids"]:
            if src not in known_sources:
                out.append(Check(BLOCK, f"{sid}: source {src} doesn't exist in the database "
                                        "(the AI may have invented it)."))
            elif src not in all_primary:
                out.append(Check(BLOCK, f"{sid}: source {src} is not a primary source for this "
                                        "episode's claims. Knowledge Fight is an index, not evidence."))
        if sc["claim_ids"] and not sc["source_ids"]:
            out.append(Check(BLOCK, f"{sid}: states facts about {', '.join(sc['claim_ids'])} "
                                    "but lists no source IDs."))
        for quote in quotes_in(sc["narration"] + " " + sc["on_screen_text"]):
            nq = normalize_for_match(quote)
            if not any(nq in normalize_for_match(excerpts[e]["text"])
                       for e in sc["excerpt_ids"] if e in excerpts):
                out.append(Check(BLOCK, f"{sid}: the quote \"{quote[:60]}...\" doesn't match any "
                                        "verified quote listed for the scene. Paraphrase it or "
                                        "list the right quote (E-number)."))
        if len(sc["on_screen_text"].split()) > 10:
            out.append(Check(WARN, f"{sid}: on-screen text is long; keep it to ~8 words."))

    roles = {sc["role"] for sc in scenes}
    for need in ("claim", "record", "benefit", "harm"):
        if need not in roles:
            out.append(Check(BLOCK, f"No scene answers '{need}'. Every video says what was "
                                    "claimed, what the record says, who benefited and what it "
                                    "did to people (mark scenes with | claim, | record, | "
                                    "benefit, | harm)."))
    narration = " ".join(sc["narration"] for sc in scenes)
    grade = reading_grade(narration)
    words = len(narration.split())
    if grade > 8:
        out.append(Check(WARN, f"Reading level is about grade {grade}; aim for 6-7. Shorter "
                               "sentences and plainer words will fix it."))
    out.append(Check(OK, f"{len(scenes)} scenes, {words} words (~{words / WORDS_PER_MINUTE:.1f} "
                         f"min), reading grade {grade}."))
    return out


def load(ep: Episode) -> dict[str, Any]:
    return parse(ep.path("script.md").read_text(encoding="utf-8"))
