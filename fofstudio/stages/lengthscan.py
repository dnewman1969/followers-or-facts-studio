"""Scan: how long should this video be to tell this story properly?

The local AI reads the chosen story and the ticked evidence and judges what the counting can't: how much
explaining each claim needs, how many timeline events and people must be introduced, how many tricks are
taught. The program then does the arithmetic (research "Film genres directors and video length"):

  fixed parts       hook 25 s + title 8 s + recap 30 s + sign-off 25 s
  context           45 s + 12 s per timeline event explained + 5 s per event mentioned + 12 s per person
  each claim        (75 s + 30 s x [1, .7, .4, .15, ...] per primary source) x complexity (1, 1.25 or 1.5)
  each trick        60 s
  + 10% for stings, cards and transitions; range +-20%; rounded to 30 s; 3 to 20 minutes.

3 minutes or less suggests a Short; more than 20 minutes (or too many claims) suggests a series. If the
honest length is 7 to 8 minutes and there's real material to add, it offers an 8-minute version (YouTube
mid-roll ads start at 8:00) - but never picks it for you, and never pads.
"""

from __future__ import annotations

import json
import math
from typing import Any

from .. import storytypes
from ..episode import Episode
from ..llm import Ollama
from ..util import StageError, read_json, utc_now, write_json
from .base import BLOCK, OK, WARN, Check, Context

SCAN_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": {"type": "object", "properties": {
            "claim_id": {"type": "string"},
            "complexity": {"type": "string", "enum": ["simple", "some explaining", "needs a lot of explaining"]},
            "why": {"type": "string"}}, "required": ["claim_id", "complexity", "why"]}},
        "timeline_events_explained": {"type": "integer", "minimum": 0, "maximum": 30},
        "timeline_events_mentioned": {"type": "integer", "minimum": 0, "maximum": 60},
        "people_introduced": {"type": "integer", "minimum": 0, "maximum": 30},
        "tricks_taught": {"type": "integer", "minimum": 1, "maximum": 5},
        "steelman": {"type": "boolean"},
        "pad_risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "split_risk": {"type": "string", "enum": ["low", "medium", "high"]},
        "reasons": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "if_shorter": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "if_longer": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
    },
    "required": ["claims", "timeline_events_explained", "timeline_events_mentioned", "people_introduced",
                 "tricks_taught", "steelman", "pad_risk", "split_risk", "reasons", "if_shorter", "if_longer"],
}
COMPLEXITY = {"simple": 1.0, "some explaining": 1.25, "needs a lot of explaining": 1.5}
SOURCE_WEIGHTS = [1.0, 0.7, 0.4]


def _round30(s: float) -> int:
    return int(round(s / 30.0) * 30)


def estimate(counts: dict[str, Any]) -> dict[str, Any]:
    """The arithmetic: counts -> honest length, range and format."""
    fixed = 25 + 8 + 30 + 25
    context = 45 + 12 * counts["events_explained"] + 5 * counts["events_mentioned"] + 12 * counts["people"]
    claims = 0.0
    for c in counts["claims"]:
        w = sum(SOURCE_WEIGHTS[i] if i < len(SOURCE_WEIGHTS) else 0.15 for i in range(c["primary_sources"]))
        claims += (75 + 30 * w) * c["complexity"]
    raw = fixed + context + claims + 60 * counts["tricks"] + (40 if counts.get("steelman") else 0)
    honest = raw * 1.10
    if counts.get("pad_risk") == "high":
        honest = min(honest, raw)                       # a thin story doesn't get stretched
    rec = max(180, min(1200, _round30(honest)))
    fmt = "short" if honest <= 180 else "series" if honest > 1200 or len(counts["claims"]) > 6 or \
        counts.get("split_risk") == "high" else "long"
    lo = max(60, min(rec, _round30(honest * 0.8)))          # the range always holds the recommendation
    hi = max(rec, min(1500, _round30(honest * 1.2)))
    out = {"honest_seconds": round(honest), "recommended_seconds": rec, "min_seconds": lo, "max_seconds": hi,
           "format": fmt, "midroll_option_seconds": None, "series_parts": max(2, math.ceil(honest / 900)),
           "parts": {"fixed": fixed, "context": round(context), "claims": round(claims),
                     "tricks": 60 * counts["tricks"], "overhead": round(raw * 0.10)}}
    if 420 <= honest < 480 and counts.get("if_longer"):
        out["midroll_option_seconds"] = 480
    return out


def primary_counts(packet: dict[str, Any]) -> dict[str, int]:
    """How many primary sources were ticked for each claim (ticked packet from research.selected)."""
    primary: dict[str, int] = {}
    for e in packet.get("evidence", []):
        if e.get("type") in ("court", "government", "primary", "document", "court_record") or e.get("is_primary"):
            primary[e["claim_id"]] = primary.get(e["claim_id"], 0) + 1
        else:
            primary.setdefault(e["claim_id"], primary.get(e["claim_id"], 0))
    for c in packet.get("claims", []):
        primary[c["claim_id"]] = max(primary.get(c["claim_id"], 0),
                                     sum(1 for s in c.get("sources", []) if s.get("is_primary")))
    return primary


def story_claims(story: dict[str, Any], packet: dict[str, Any]) -> set[str]:
    """The claims the chosen story's beats lean on (their evidence IDs belong to them)."""
    want = {e for b in story.get("beats", []) for e in b.get("evidence_ids", [])}
    out = set()
    for c in packet.get("claims", []):
        ids = {s["source_id"] for s in c.get("sources", [])} | {f"E{x['excerpt_id']}" for x in c.get("excerpts", [])}
        if want & ids:
            out.add(c["claim_id"])
    for e in packet.get("evidence", []):
        if e["id"] in want:
            out.add(e["claim_id"])
    return out


def counts_from(ep: Episode, story: dict[str, Any], judged: dict[str, Any]) -> dict[str, Any]:
    from .research import selected
    packet = selected(read_json(ep.path("research.json")) or {})
    primary = primary_counts(packet)
    focus = story_claims(story, packet)
    if focus:      # the video tells the chosen story, not everything that was ticked
        packet = {**packet, "claims": [c for c in packet["claims"] if c["claim_id"] in focus]}
    judged_c = {c["claim_id"]: COMPLEXITY.get(c["complexity"], 1.25) for c in judged.get("claims", [])}
    claims = [{"claim_id": c["claim_id"], "primary_sources": primary.get(c["claim_id"], 0),
               "complexity": judged_c.get(c["claim_id"], 1.25)} for c in packet.get("claims", [])]
    return {"claims": claims, "events_explained": int(judged.get("timeline_events_explained", 3)),
            "events_mentioned": int(judged.get("timeline_events_mentioned", 3)),
            "people": int(judged.get("people_introduced", 2)),
            "tricks": max(1, min(3, int(judged.get("tricks_taught", len(story.get("techniques", [])) or 1)))),
            "steelman": bool(judged.get("steelman")), "pad_risk": judged.get("pad_risk", "low"),
            "split_risk": judged.get("split_risk", "low"), "if_longer": judged.get("if_longer", [])}


def run(ctx: Context) -> None:
    ep = ctx.episode
    from .stories import chosen, evidence_for_prompt
    story = chosen(ep)
    if not story:
        raise StageError("Pick a story on the Stories page first.")
    stype = storytypes.STORY_TYPES.get(story.get("story_type") or "") or storytypes.STORY_TYPES[storytypes.DEFAULT_TYPE]
    ctx.progress("Reading the story and the ticked evidence", 5)
    judged = Ollama(job="script_plan").chat_json([
        {"role": "system", "content": (
            "You are a documentary producer judging how much screen time a fact-check video needs. Don't pad: every "
            "second must be earned by a claim, a source, an event, a person or a trick in the material. Judge each "
            "claim's complexity (simple, some explaining, needs a lot of explaining) with a one-line reason; count the "
            "timeline events that must be explained or just mentioned, and the people who must be introduced; say "
            "whether the believers' best case should be shown; say if the story is thin (pad risk) or too big for "
            "one video (split risk); list what to cut if it must be shorter and what real material could be added "
            "if longer. Judge only what THIS story tells (its beats), not everything in the evidence. Use only the "
            "material given.")},
        {"role": "user", "content": f"Story ({stype.name}):\n{json.dumps(story, ensure_ascii=False)[:6000]}\n\n"
                                    f"Evidence:\n{evidence_for_prompt(ep)[:14000]}"},
    ], SCAN_SCHEMA, temperature=0.3, on_text=ctx.writing("Scanning the story", 10, 85, 400))
    counts = counts_from(ep, story, judged)
    est = estimate(counts)
    beats = [{"beat": b.name, "role": b.role, "seconds": round(est["recommended_seconds"] * b.share / 100)}
             for b in stype.beats]
    result = {**est, "counts": counts, "judged": judged, "beats": beats, "story_type": stype.key,
              "made_at": utc_now()}
    write_json(ep.path("scan.json"), result)
    ep.set_creative(minutes=round(est["recommended_seconds"] / 60, 1))
    ctx.progress(f"About {est['recommended_seconds'] / 60:.1f} minutes is right for this story "
                 f"({est['min_seconds'] / 60:.1f} to {est['max_seconds'] / 60:.1f}). Set your length, then "
                 "Produce script.", 100)


def load(ep: Episode) -> dict[str, Any]:
    return read_json(ep.path("scan.json"), {}) or {}


def check(ep: Episode) -> list[Check]:
    s = load(ep)
    if not s:
        return [Check(BLOCK, "Not scanned yet.")]
    out = [Check(OK, f"Recommended {s['recommended_seconds'] / 60:.1f} min.")]
    if s["format"] != "long":
        out.append(Check(WARN, "This story suits a " + ("YouTube Short." if s["format"] == "short" else "series of videos.")))
    return out


def summary_html(s: dict[str, Any]) -> str:
    """The scan result for the Script page."""
    if not s:
        return ""
    import html
    e = html.escape
    rec, lo, hi = s["recommended_seconds"] / 60, s["min_seconds"] / 60, s["max_seconds"] / 60
    full = s.get("honest_seconds", 0) / 60
    parts = [f"<b>Best length for this story: about {rec:.1f} minutes</b> (anything from {lo:.1f} to {hi:.1f} works)."]
    if s["format"] == "short":
        parts.append("It's thin enough to work as a YouTube Short (3 minutes or less).")
    elif s["format"] == "series" and full > rec + 0.5:
        parts.append(f"Telling all of it properly would take about {full:.0f} minutes, and 20 is the most for one "
                     f"video: think about {s.get('series_parts', 2)} parts, each with its own verdict, or keep this one "
                     "to the main thread (see what to cut below).")
    elif s["format"] == "series":
        parts.append("It has a lot of claims for one video: think about splitting it into parts, each with its own "
                     "verdict.")
    if s.get("midroll_option_seconds"):
        parts.append("There's real material to reach 8:00, where YouTube allows mid-video ads - only if you want it.")
    j = s.get("judged", {})
    if j.get("reasons"):
        parts.append("<br>Why: " + "; ".join(e(r) for r in j["reasons"][:4]))
    if j.get("if_shorter"):
        parts.append("<br>If you go shorter, cut: " + "; ".join(e(r) for r in j["if_shorter"][:3]))
    if j.get("if_longer"):
        parts.append("<br>If you go longer, add: " + "; ".join(e(r) for r in j["if_longer"][:3]))
    return " ".join(parts)
