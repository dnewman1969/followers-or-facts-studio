"""How big is this story? Short, one video, a series, or a whole book.

When the research goes to the story writer, the local AI first reads all the ticked evidence and judges
what counting can't: how much explaining each claim needs, how many timeline events and people there are,
and how many separate threads the story has. The program then does the arithmetic:

  video length   the Script page's length formula (lengthscan.estimate), with no 20-minute cap
  book pages     450 words per claim + 220 per source + 100 per quote + 120 per person or group
                 + 100 per timeline event, at 300 words a page

  Short    the honest telling is 3 minutes or less
  Video    up to 20 minutes, at most 6 claims, at most 2 threads
  Series   more than that: parts of about 15 minutes, each with its own verdict
  Book     enough material for [book] min_pages pages (45 by default) and at least 3 claims or 15 sources

A book-sized subject still gets its three video stories (a video is the way into the book).
"""

from __future__ import annotations

import json
import math
from typing import Any

from ..config import settings
from ..episode import Episode
from ..llm import Ollama
from ..util import read_json, utc_now, write_json
from . import lengthscan

SIZE_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": {"type": "object", "properties": {
            "claim_id": {"type": "string"},
            "complexity": {"type": "string", "enum": list(lengthscan.COMPLEXITY)}},
            "required": ["claim_id", "complexity"]}},
        "timeline_events": {"type": "integer", "minimum": 0, "maximum": 200},
        "people_and_groups": {"type": "integer", "minimum": 0, "maximum": 100},
        "threads": {"type": "integer", "minimum": 1, "maximum": 12},
        "reasons": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "parts": {"type": "array", "maxItems": 8, "items": {"type": "object", "properties": {
            "title": {"type": "string"}, "claim_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["title", "claim_ids"]}},
    },
    "required": ["claims", "timeline_events", "people_and_groups", "threads", "reasons", "parts"],
}
FORMATS = {"short": "a YouTube Short", "video": "one video", "series": "a series of videos", "book": "a book"}
WORDS_PER_PAGE = 300


def material(packet: dict[str, Any]) -> dict[str, int]:
    """Plain counts of what was ticked."""
    ev = packet.get("evidence", [])
    sources = {e["source_id"] for e in ev}
    people = {p["person_id"] for c in packet.get("claims", []) for p in c.get("people", [])}
    orgs = {o["org_id"] for c in packet.get("claims", []) for o in c.get("orgs", [])}
    return {"claims": len(packet.get("claims", [])), "sources": len(sources),
            "quotes": sum(1 for e in ev if e.get("kind") == "quote"), "people_and_groups": len(people | orgs)}


def pages_for(m: dict[str, int], events: int, people: int) -> int:
    words = 450 * m["claims"] + 220 * m["sources"] + 100 * m["quotes"] + 120 * people + 100 * events
    return max(1, round(words / WORDS_PER_PAGE))


def decide(m: dict[str, int], judged: dict[str, Any], primary: dict[str, int]) -> dict[str, Any]:
    """The arithmetic: counts and the AI's judgement -> format, minutes, pages."""
    complexity = {c["claim_id"]: lengthscan.COMPLEXITY.get(c.get("complexity"), 1.25)
                  for c in judged.get("claims", [])}
    events = int(judged.get("timeline_events", 0))
    people = max(int(judged.get("people_and_groups", 0)), m["people_and_groups"])
    threads = int(judged.get("threads", 1))
    claims = [{"claim_id": cid, "primary_sources": n, "complexity": complexity.get(cid, 1.25)}
              for cid, n in primary.items()]
    explained = round(events * 0.6)
    est = lengthscan.estimate({"claims": claims, "events_explained": min(explained, 30),
                               "events_mentioned": events - explained, "people": people,
                               "tricks": 2 if threads > 1 else 1, "steelman": False, "pad_risk": "low",
                               "split_risk": "high" if threads > 2 else "low", "if_longer": []})
    # the formula stops counting events and people at a video's worth; a book doesn't
    seconds = est["honest_seconds"] + 7 * max(0, events - 30)
    pages = pages_for(m, events, people)
    cfg = settings().get("book", {})
    min_pages = int(cfg.get("min_pages", 45))
    if pages >= min_pages and (m["claims"] >= 3 or m["sources"] >= 15):
        fmt = "book"
    elif seconds <= 180:
        fmt = "short"
    elif seconds <= 1200 and m["claims"] <= 6 and threads <= 2:
        fmt = "video"
    else:
        fmt = "series"
    parts = max(2, math.ceil(seconds / 900)) if fmt in ("series", "book") else 1
    return {"format": fmt, "video_seconds": round(seconds), "series_parts": parts, "pages": pages,
            "chapters": max(5, min(16, 4 + m["claims"] + m["sources"] // 12)), "min_book_pages": min_pages,
            "threads": threads, "timeline_events": events, "people_and_groups": people}


def assess(ep: Episode, packet: dict[str, Any], evidence_text: str, llm: Ollama | None = None,
           on_text=None) -> dict[str, Any]:
    """Read everything once and say how big it is. Saved to size.json (and shown on the Stories page)."""
    m = material(packet)
    llm = llm or Ollama(job="stories")
    judged = llm.chat_json([
        {"role": "system", "content": (
            "You are the head writer of a fact-check channel deciding how big a story is before anyone writes it. "
            "Read all the evidence. For each claim judge how much explaining it needs. Count the separate events "
            "on the timeline (from where it started to today), the people and groups involved, and the separate "
            "threads (storylines that could each stand alone). Give up to 5 short reasons, and if it's too big "
            "for one video, the parts it would split into (each with the claim IDs it covers). Use only the "
            "material given; don't pad and don't shrink.")},
        {"role": "user", "content": f"Material:\n{evidence_text[:30000]}"},
    ], SIZE_SCHEMA, temperature=0.2, on_text=on_text)
    valid = {c["claim_id"] for c in packet.get("claims", [])}
    judged["claims"] = [c for c in judged.get("claims", []) if c.get("claim_id") in valid]
    judged["parts"] = [dict(p, claim_ids=[c for c in p.get("claim_ids", []) if c in valid])
                       for p in judged.get("parts", []) if p.get("title")]
    primary = lengthscan.primary_counts(packet)
    out = {**decide(m, judged, primary), "material": m, "reasons": judged.get("reasons", [])[:5],
           "parts": judged["parts"][:8], "made_at": utc_now()}
    write_json(ep.path("size.json"), out)
    return out


def load(ep: Episode) -> dict[str, Any]:
    return read_json(ep.path("size.json"), {}) or {}


def summary_html(s: dict[str, Any]) -> str:
    """The size verdict for the Stories page, in plain words."""
    if not s:
        return ""
    import html
    e = html.escape
    m = s.get("material", {})
    mins = s["video_seconds"] / 60
    have = (f"{m.get('claims', 0)} claims, {m.get('sources', 0)} sources, {m.get('quotes', 0)} word-for-word "
            f"quotes, {s.get('people_and_groups', 0)} people and groups, about {s.get('timeline_events', 0)} "
            "events on the timeline")
    fmt = s["format"]
    if fmt == "book":
        head = (f"📚 <b>This subject is big enough for a book</b>: about {s['pages']} pages in "
                f"{s['chapters']} chapters. Telling all of it on video would take about {mins:.0f} minutes "
                f"({s['series_parts']} parts). The three stories below are video ways in; press "
                "<b>Write the book</b> for the full breakdown with references.")
    elif fmt == "series":
        head = (f"<b>Too big for one video</b>: about {mins:.0f} minutes to tell properly, so think about "
                f"{s['series_parts']} parts, each with its own verdict. A book would be about {s['pages']} pages.")
    elif fmt == "short":
        head = f"<b>Small and sharp</b>: about {mins:.1f} minutes, so it could be a YouTube Short."
    else:
        head = f"<b>One video</b>: about {mins:.0f} minutes tells it properly."
    parts = [head, f"<br>What there is to work with: {e(have)}."]
    if s.get("reasons"):
        parts.append("<br>Why: " + "; ".join(e(r) for r in s["reasons"][:4]))
    if fmt in ("series", "book") and s.get("parts"):
        parts.append("<br>Parts: " + "; ".join(f"{k + 1}. {e(p['title'])}" for k, p in enumerate(s["parts"][:8])))
    if fmt != "book":
        parts.append(f"<br><span>A book needs about {s['min_book_pages']} pages of material; this has about "
                     f"{s['pages']}. You can still write one, but it will be thin.</span>")
    return " ".join(parts)


def describe(s: dict[str, Any]) -> str:
    return json.dumps({k: s.get(k) for k in ("format", "video_seconds", "pages")})
