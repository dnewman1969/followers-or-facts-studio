"""Stage 2 - Script.

The local AI drafts the script from the research packet only. Every scene
carries the claim IDs and source IDs it relies on, and quotes may only come
from verified excerpts. You can edit script.md by hand and press Re-check.
"""

from __future__ import annotations

import json
import re
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
2. Every scene that states a fact lists the claim_ids and source_ids it relies on. source_ids
   are the "source_id" values in the packet (they start with "S-"), only ones listed under that
   claim. Quote numbers like E14 are NOT source IDs: put the number (14) in excerpt_ids instead.
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


def selected_packet(ep: Episode) -> dict[str, Any]:
    from .research import selected
    return selected(read_json(ep.path("research.json")) or {"claims": [], "evidence": []})


def _excerpt_map(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(e["excerpt_id"]): e for c in packet.get("claims", []) for e in c.get("excerpts", [])}


def fix_refs(sc: dict[str, Any], packet: dict[str, Any], fill: bool = True) -> list[str]:
    """Tidy one scene's SOURCES line: quote numbers written as sources (E14) become the quote's
    source plus the quote number, and a scene with sources but no claims gets the claims those
    sources belong to. Returns notes about anything it had to fill in."""
    notes = []
    excerpts = _excerpt_map(packet)
    claim_of = {s["source_id"]: c["claim_id"] for c in packet.get("claims", []) for s in c["sources"]}
    srcs, quotes = [], [str(q).lstrip("Ee") for q in sc.get("excerpt_ids", [])]
    for ref in sc.get("source_ids", []):
        ref = str(ref).strip()
        m = re.fullmatch(r"[Ee](\d+)", ref)
        if m:
            quotes.append(m.group(1))
            if m.group(1) in excerpts:
                ref = excerpts[m.group(1)]["source_id"]
            else:
                srcs.append(ref)  # leave it for the check to flag
                continue
        srcs.append(ref)
    for q in quotes:  # a quote implies its source
        if q in excerpts and excerpts[q]["source_id"] not in srcs:
            srcs.append(excerpts[q]["source_id"])
    sc["source_ids"] = list(dict.fromkeys(srcs))
    sc["excerpt_ids"] = list(dict.fromkeys(quotes))
    if sc["source_ids"] and not sc.get("claim_ids"):
        sc["claim_ids"] = list(dict.fromkeys(claim_of[s] for s in sc["source_ids"] if s in claim_of))
    if fill and sc.get("claim_ids") and not sc["source_ids"]:
        for cid in sc["claim_ids"]:
            c = next((c for c in packet.get("claims", []) if c["claim_id"] == cid), None)
            if c and c["sources"]:
                best = sorted(c["sources"], key=lambda s: (not s.get("is_primary"), s["source_id"]))[:2]
                sc["source_ids"] += [s["source_id"] for s in best]
                notes.append(f"{sc.get('scene_id', '?')}: no sources given for {cid}; used "
                             f"{', '.join(s['source_id'] for s in best)} (your ticked evidence for it). Check they fit.")
    return notes


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
                         "publisher": s.get("publisher"), "date": s.get("date"),
                         "what_it_shows": s.get("summary") or s.get("supports_field") or ""}
                        for s in c["sources"]],
            "verified_quotes": [{"excerpt_id": e["excerpt_id"], "source_id": e["source_id"],
                                 "text": e["text"]} for e in c["excerpts"]],
        })
    return json.dumps(slim, ensure_ascii=False, indent=1)


def run(ctx: Context) -> None:
    ep = ctx.episode
    if not ep.path("research.json").exists():
        raise StageError("Run and approve the Research stage first.")
    packet = selected_packet(ep)
    if not packet["claims"]:
        raise StageError("No evidence is ticked on the Research page.")
    from .stories import chosen
    story = chosen(ep)
    minutes = float(ctx.options.get("minutes", 8))
    words = int(minutes * WORDS_PER_MINUTE)
    ctx.progress(f"Writing a ~{minutes:g} minute script with {settings()['ollama']['writer_model']}", 10)
    story_text = ""
    if story:
        excerpts = _excerpt_map(packet)
        beats = []
        for b in story.get("beats", []):
            src, quotes = [], []
            for ref in b.get("evidence_ids", []):
                m = re.fullmatch(r"E(\d+)", ref)
                if m and m.group(1) in excerpts:
                    quotes.append(int(m.group(1)))
                    src.append(excerpts[m.group(1)]["source_id"])
                elif not m:
                    src.append(ref)
            beats.append({"role": b["role"], "beat": b["beat"], "source_ids": list(dict.fromkeys(src)),
                          "excerpt_ids": quotes})
        plan = {k: story[k] for k in ("title", "logline", "angle", "opening_hook")}
        plan["beats"] = beats
        story_text = ("\nFollow this approved story plan, beat by beat (one or more scenes per beat). Each "
                      "beat lists the source_ids and excerpt_ids to use for it:\n"
                      + json.dumps(plan, ensure_ascii=False, indent=1) + "\n")
    answer = Ollama().chat_json([
        {"role": "system", "content": VOICE_RULES},
        {"role": "user", "content": (
            f"Episode working title: {story['title'] if story else ep.title}\n"
            f"Target length: about {words} words of narration in 6 to 12 scenes. Owlbert narrates "
            "everything in the first person as the curious owl professor.\n"
            + (f"Extra direction from the producer: {ctx.options['direction']}\n"
               if ctx.options.get("direction") else "")
            + story_text
            + f"\nResearch packet:\n{_packet_for_prompt(packet)}")},
    ], SCRIPT_SCHEMA, temperature=0.6,
        # the answer also carries picture descriptions and source lists: roughly twice the narration
        on_text=ctx.writing("Writing the script", 10, 95, expect_words=words * 2))
    scenes = answer.get("scenes") or []
    if len(scenes) < 3:
        raise StageError("The draft came back with fewer than 3 scenes. Run the stage again.")
    for n, sc in enumerate(scenes, 1):
        sc["scene_id"] = f"SCENE_{n:03d}"
        sc["est_seconds"] = round(len(sc.get("narration", "").split()) / WORDS_PER_MINUTE * 60)
        for note in fix_refs(sc, packet):
            ctx.log(note)
    header = {"Episode": ep.project_id, "Arc": (packet.get("arc") or {}).get("arc_id", "-"),
              "Drafted by": settings()["ollama"]["writer_model"]}
    write_text(ep.path("script.md"), render(answer.get("title") or ep.title, scenes, header))
    ctx.log(f"Draft written: {len(scenes)} scenes. Read and edit script.md, then Re-check.")


def check(ep: Episode) -> list[Check]:
    path = ep.path("script.md")
    if not path.exists():
        return [Check(BLOCK, "No script yet. Run this stage (or write script.md yourself).")]
    packet = selected_packet(ep)
    raw_ev = (read_json(ep.path("research.json")) or {}).get("evidence", [])
    script = parse(path.read_text(encoding="utf-8"))
    scenes = script["scenes"]
    out: list[Check] = []
    if not scenes:
        return [Check(BLOCK, "script.md has no '## SCENE_###' headings.")]

    claim_sources = {c["claim_id"]: {s["source_id"] for s in c["sources"]} for c in packet["claims"]}
    all_ticked = set().union(*claim_sources.values()) if claim_sources else set()
    excerpts = _excerpt_map(packet)
    known_sources = {r["source_id"] for r in db.rows("SELECT source_id FROM source")}
    kf = {r["source_id"] for r in db.rows("SELECT source_id FROM source WHERE source_type='kf_index'")}
    all_claims = {r["claim_id"] for r in db.rows("SELECT claim_id FROM claim")}

    for sc in scenes:
        sid = sc["scene_id"]
        fix_refs(sc, packet, fill=False)  # read E-numbers in the sources list as quotes (for hand edits)
        for cid in sc["claim_ids"]:
            if cid not in claim_sources:
                why = ("has nothing ticked on the Research page" if cid in all_claims
                       else "isn't in the database (the AI may have invented it)")
                out.append(Check(BLOCK, f"{sid}: claim {cid} {why}."))
        for src in sc["source_ids"]:
            if re.fullmatch(r"[Ee]\d+", src):
                out.append(Check(BLOCK, f"{sid}: quote {src} isn't one of the quotes you ticked on the Research page."))
            elif src not in known_sources:
                out.append(Check(BLOCK, f"{sid}: source {src} doesn't exist in the database "
                                        "(the AI may have invented it)."))
            elif src in kf:
                out.append(Check(BLOCK, f"{sid}: source {src} is a Knowledge Fight episode. It's a research "
                                        "index, not evidence."))
            elif src not in all_ticked:
                title = next((e.get("title") for e in raw_ev if e["source_id"] == src), None)
                if title:
                    out.append(Check(BLOCK, f"{sid} uses \"{title[:60]}\", which isn't ticked. "
                                            "Press Tick what the script needs, or take it out of this scene."))
                else:
                    out.append(Check(BLOCK, f"{sid}: source {src} isn't part of this video's research (the AI "
                                            "brought it in). Take it out of this scene."))
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


def wanted_unticked(ep: Episode) -> dict[str, list[str]]:
    """Evidence the script uses that isn't ticked on the Research page: {evidence id: [scenes]}.
    For a source, the item to tick is its link row (or, failing that, its quote rows)."""
    path = ep.path("script.md")
    raw = read_json(ep.path("research.json")) or {}
    evidence = raw.get("evidence", [])
    if not path.exists() or not evidence:
        return {}
    ticked_sources = {e["source_id"] for e in evidence if e.get("include")}
    ticked_ids = {e["id"] for e in evidence if e.get("include")}
    full = {**raw, "claims": raw.get("claims", [])}  # E-numbers resolve against everything on file
    out: dict[str, list[str]] = {}
    for sc in parse(path.read_text(encoding="utf-8"))["scenes"]:
        fix_refs(sc, full, fill=False)
        for src in sc["source_ids"]:
            if src in ticked_sources:
                continue
            rows = [e for e in evidence if e["source_id"] == src]
            pick = [e for e in rows if e["kind"] == "link"] or rows
            for e in pick:
                out.setdefault(e["id"], []).append(sc["scene_id"])
        for q in sc["excerpt_ids"]:
            eid = f"E{q}"
            if eid not in ticked_ids and any(e["id"] == eid for e in evidence):
                out.setdefault(eid, []).append(sc["scene_id"])
    return {k: list(dict.fromkeys(v)) for k, v in out.items()}


def load(ep: Episode) -> dict[str, Any]:
    return parse(ep.path("script.md").read_text(encoding="utf-8"))
