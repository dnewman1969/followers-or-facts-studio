"""Stage 1 - Research packet.

Pulls the episode's claims, their sources, people, Knowledge Fight references
and careful-topic rules out of the database; saves copies of the primary
sources; and has the local AI propose supporting quotes, which are kept only if
they appear word for word in the saved copy.
"""

from __future__ import annotations

from typing import Any

from .. import db, sources
from ..episode import Episode
from ..llm import Ollama
from ..util import read_json, utc_now, write_json, write_text
from .base import BLOCK, OK, WARN, Check, Context

EXCERPT_SCHEMA = {
    "type": "object",
    "properties": {
        "excerpts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "supports": {"type": "string"},
                },
                "required": ["quote", "supports"],
            },
        }
    },
    "required": ["excerpts"],
}


def restrictions_for(claim_ids: list[str], arc_id: str | None) -> list[dict[str, Any]]:
    params: list[Any] = list(claim_ids)
    sql = ("SELECT * FROM content_restriction WHERE (subject_type='claim' AND subject_id IN (%s))"
           % ",".join("?" * len(claim_ids)) if claim_ids else
           "SELECT * FROM content_restriction WHERE 0")
    if arc_id:
        sql += " OR (subject_type='arc' AND subject_id=?)"
        params.append(arc_id)
    return db.rows(sql, tuple(params))


def build_packet(ep: Episode) -> dict[str, Any]:
    claim_ids = ep.claim_ids
    claims = []
    for cid in claim_ids:
        c = db.one("SELECT * FROM claim WHERE claim_id=?", (cid,))
        if not c:
            continue
        srcs = db.rows("""SELECT s.source_id, s.title, s.publisher, s.date, s.url, s.source_type,
                                 s.reliability, s.is_primary, s.text_path, s.accessed_at,
                                 s.http_status, cs.supports_field
                          FROM claim_source cs JOIN source s ON s.source_id = cs.source_id
                          WHERE cs.claim_id=? ORDER BY s.is_primary DESC, s.source_id""", (cid,))
        people = db.rows("""SELECT ce.link_role, p.person_id, p.name FROM claim_entity ce
                            JOIN person p ON p.person_id = ce.entity_id
                            WHERE ce.claim_id=? AND ce.entity_type='person'""", (cid,))
        orgs = db.rows("""SELECT ce.link_role, o.org_id, o.name FROM claim_entity ce
                          JOIN organization o ON o.org_id = ce.entity_id
                          WHERE ce.claim_id=? AND ce.entity_type='org'""", (cid,))
        kf = db.rows("""SELECT k.kf_ep, k.title, k.air_date FROM kf_episode_link l
                        JOIN kf_episode k ON k.kf_ep = l.kf_ep
                        WHERE l.entity_type='claim' AND l.entity_id=? ORDER BY k.kf_ep_num""", (cid,))
        excerpts = db.rows("SELECT excerpt_id, source_id, text, verified FROM source_excerpt "
                           "WHERE claim_id=? AND verified=1 ORDER BY excerpt_id", (cid,))
        claims.append({**c, "sources": srcs, "people": people, "orgs": orgs,
                       "kf_episodes": kf, "excerpts": excerpts})
    arc = db.one("SELECT * FROM arc WHERE arc_id=?", (ep.info.get("arc_id"),)) if ep.info.get("arc_id") else None
    return {
        "project_id": ep.project_id,
        "title": ep.title,
        "arc": arc,
        "claims": claims,
        "restrictions": restrictions_for(claim_ids, ep.info.get("arc_id")),
        "built_at": utc_now(),
    }


def _find_excerpts(ctx: Context, packet: dict[str, Any]) -> tuple[int, int]:
    llm = Ollama()
    kept = rejected = 0
    for claim in packet["claims"]:
        for src in claim["sources"]:
            ctx.check_cancel()
            if not src["is_primary"]:
                continue
            text = sources.source_text(src["source_id"])
            if not text:
                continue
            query = " ".join(str(claim.get(k) or "") for k in
                             ("short_title", "claim_summary", "harm_summary", "who_benefited"))
            passages = sources.relevant_passages(text, query)
            if not passages:
                continue
            ctx.progress(f"Finding quotes: {claim['claim_id']} in {src['source_id']}")
            answer = llm.chat_json([
                {"role": "system", "content": (
                    "You copy sentences out of a document. Copy them EXACTLY, character for "
                    "character. Never paraphrase, never fix typos, never join sentences from "
                    "different places. If nothing in the document is relevant, return an empty list.")},
                {"role": "user", "content": (
                    f"Claim being fact-checked: {claim['short_title']}\n"
                    f"Summary: {claim.get('claim_summary') or ''}\n\n"
                    f"Document ({src['title']}, {src.get('publisher') or ''}):\n<<<\n{passages}\n>>>\n\n"
                    "Copy up to 3 sentences from the document that best show what the record "
                    "actually says about this claim. For each, say in a few words what it supports.")},
            ], EXCERPT_SCHEMA, temperature=0.1)
            for item in answer.get("excerpts", [])[:3]:
                quote = (item.get("quote") or "").strip()
                if len(quote) < 20:
                    continue
                _, ok = sources.add_excerpt(src["source_id"], quote, claim["claim_id"])
                if ok:
                    kept += 1
                else:
                    rejected += 1
    return kept, rejected


def run(ctx: Context) -> None:
    ep = ctx.episode
    if not ep.claim_ids:
        from ..util import StageError
        raise StageError("This episode has no claims. Pick claims on the Episode page first.")
    packet = build_packet(ep)

    if ctx.options.get("fetch_sources", True):
        todo = [s for c in packet["claims"] for s in c["sources"] if s["is_primary"]]
        seen: set[str] = set()
        for n, src in enumerate(todo, 1):
            ctx.check_cancel()
            if src["source_id"] in seen:
                continue
            seen.add(src["source_id"])
            ctx.progress(f"Saving source copies {n}/{len(todo)}: {src['source_id']}")
            result = sources.fetch_source(src["source_id"], refresh=ctx.options.get("refresh", False))
            if not result["ok"]:
                ctx.log(f"  {src['source_id']}: could not save ({result.get('error')})")
        packet = build_packet(ep)

    if ctx.options.get("find_quotes", True):
        kept, rejected = _find_excerpts(ctx, packet)
        ctx.log(f"Quotes: kept {kept} that match the saved sources word for word; "
                f"threw away {rejected} that didn't.")
        packet = build_packet(ep)

    write_json(ep.path("research.json"), packet)
    write_text(ep.path("research.md"), render_markdown(packet))


def render_markdown(packet: dict[str, Any]) -> str:
    lines = [f"# Research packet: {packet['title']}", ""]
    if packet.get("arc"):
        lines += [f"**Arc:** {packet['arc']['arc_id']} - {packet['arc']['title']}", ""]
    if packet["restrictions"]:
        lines += ["## Careful-topic rules", ""]
        lines += [f"- **{r['rule']}** ({r['subject_id']}): {r['note'] or ''}" for r in packet["restrictions"]]
        lines.append("")
    for c in packet["claims"]:
        prim = [s for s in c["sources"] if s["is_primary"]]
        lines += [f"## {c['claim_id']}: {c['short_title']}", "",
                  f"- **Verdict in database:** {c['falsity_status']}",
                  f"- **Claim:** {c.get('claim_summary') or ''}",
                  f"- **Harm:** {c.get('harm_summary') or ''}",
                  f"- **Who benefited:** {c.get('who_benefited') or ''}",
                  f"- **Primary sources:** {len(prim)}", ""]
        for s in c["sources"]:
            saved = "saved" if s.get("text_path") else "not saved"
            lines.append(f"  - {s['source_id']} [{s['source_type']}] {s['title']} "
                         f"({s.get('publisher') or ''}, {s.get('date') or ''}) {s.get('url') or ''} - {saved}")
        if c["excerpts"]:
            lines += ["", "  Verified quotes:"]
            lines += [f"  - E{e['excerpt_id']} ({e['source_id']}): \"{e['text']}\"" for e in c["excerpts"]]
        if c["kf_episodes"]:
            lines += ["", "  Knowledge Fight (index only): " +
                      ", ".join(f"#{k['kf_ep']}" for k in c["kf_episodes"])]
        lines.append("")
    return "\n".join(lines)


def check(ep: Episode) -> list[Check]:
    packet = read_json(ep.path("research.json"))
    if not packet:
        return [Check(BLOCK, "No research packet yet. Run this stage.")]
    out: list[Check] = []
    if not packet["claims"]:
        out.append(Check(BLOCK, "The episode has no claims."))
    rules = {(r["subject_type"], r["subject_id"], r["rule"]) for r in packet["restrictions"]}
    arc_id = (packet.get("arc") or {}).get("arc_id")
    for c in packet["claims"]:
        prim = [s for s in c["sources"] if s["is_primary"]]
        if not prim:
            out.append(Check(BLOCK, f"{c['claim_id']} has no primary source (court, wire, gov, "
                                    "journalism, academic, museum or archive audio). Add one in "
                                    "the Research page or drop the claim from this episode."))
        courts_only = ("claim", c["claim_id"], "courts_only") in rules or \
                      ("arc", arc_id, "courts_only") in rules
        if courts_only and not any(s["source_type"] in ("court", "gov") for s in prim):
            out.append(Check(BLOCK, f"{c['claim_id']} is a victims topic (courts only) but has "
                                    "no court or government source."))
        if prim and not any(s.get("text_path") for s in prim):
            out.append(Check(WARN, f"{c['claim_id']}: no primary source copy saved, so its "
                                   "quotes can't be checked. The script must paraphrase."))
        if c["falsity_status"] in ("unverified", "contested"):
            out.append(Check(WARN, f"{c['claim_id']} is '{c['falsity_status']}' - the script "
                                   "must say that plainly, not call it false."))
    for r in packet["restrictions"]:
        out.append(Check(WARN, f"Careful topic: {r['rule']} on {r['subject_id']}. {r.get('note') or ''}"))
    if not any(c.level == BLOCK for c in out):
        out.append(Check(OK, f"{len(packet['claims'])} claims, all with primary sources."))
    return out
