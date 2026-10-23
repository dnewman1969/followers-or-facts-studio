"""Research: the agents dig up the proof.

1. Sources already in the database: save a copy of each (from the live web, or from the
   Wayback Machine if the page is gone) and find quotes in it.
2. For every claim, the local AI plans searches; the agents search the web (DuckDuckGo,
   Bing, Brave... through the free ddgs library), CourtListener court records, the Federal
   Register and the Library of Congress (plus Google Fact Check if you add a free key);
   read the best hits; and pull exact quotes.
3. A quote is kept only if it appears word for word in the saved page. The AI never
   writes a link: every link comes from a search result or the database.
4. Every link gets a Wayback Machine copy, so the proof in the YouTube description
   still works years from now.
New finds go into the database as new sources, marked "found by the research agent".
You approve the list (and untick anything you don't want in the description).
"""

from __future__ import annotations

import hashlib
from typing import Any

from .. import db, sources
from ..agents import search, web
from ..config import settings
from ..episode import Episode
from ..llm import Ollama
from ..util import StageError, read_json, utc_now, write_json, write_text
from .base import BLOCK, OK, WARN, Check, Context

EXCERPT_SCHEMA = {
    "type": "object",
    "properties": {"excerpts": {"type": "array", "items": {"type": "object", "properties": {
        "quote": {"type": "string"}, "supports": {"type": "string"}}, "required": ["quote", "supports"]}}},
    "required": ["excerpts"],
}
QUERY_SCHEMA = {
    "type": "object",
    "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
    "required": ["queries"],
}
DEPTH = {"quick": (2, 3), "normal": (4, 5), "deep": (6, 8)}   # searches, new pages read, per claim


def restrictions_for(claim_ids: list[str], arc_id: str | None) -> list[dict[str, Any]]:
    arcs = {arc_id} if arc_id else set()
    for cid in claim_ids:
        row = db.one("SELECT arc_id FROM claim WHERE claim_id=?", (cid,))
        if row and row["arc_id"]:
            arcs.add(row["arc_id"])
    out = []
    for cid in claim_ids:
        out += db.rows("SELECT * FROM content_restriction WHERE subject_type='claim' AND subject_id=?", (cid,))
    for a in sorted(arcs):
        out += db.rows("SELECT * FROM content_restriction WHERE subject_type='arc' AND subject_id=?", (a,))
    return out


def build_packet(ep: Episode) -> dict[str, Any]:
    claim_ids = ep.claim_ids
    claims = []
    for cid in claim_ids:
        c = db.one("SELECT * FROM claim WHERE claim_id=?", (cid,))
        if not c:
            continue
        srcs = db.rows("""SELECT s.source_id, s.title, s.publisher, s.date, s.url, s.source_type, s.reliability,
                                 s.is_primary, s.text_path, s.accessed_at, s.http_status, s.archive_url, s.found_by,
                                 cs.supports_field
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
        excerpts = db.rows("SELECT excerpt_id, source_id, text, verified, supports FROM source_excerpt "
                           "WHERE claim_id=? AND verified=1 ORDER BY excerpt_id", (cid,))
        claims.append({**c, "sources": srcs, "people": people, "orgs": orgs, "kf_episodes": kf, "excerpts": excerpts})
    info = ep.info
    proj = db.one("SELECT subject_type, subject_id FROM project WHERE project_id=?", (ep.project_id,)) or {}
    arc = db.one("SELECT * FROM arc WHERE arc_id=?", (info.get("arc_id"),)) if info.get("arc_id") else None
    old = read_json(ep.path("research.json")) or {}
    excluded = {e["id"] for e in old.get("evidence", []) if not e.get("include", True)}
    return {
        "project_id": ep.project_id, "title": ep.title, "arc": arc,
        "subject": {"kind": proj.get("subject_type") or ("story" if arc else "conspiracy"),
                    "id": proj.get("subject_id") or info.get("arc_id"), "title": ep.title},
        "claims": claims,
        "evidence": evidence_list(claims, excluded),
        "restrictions": restrictions_for(claim_ids, info.get("arc_id")),
        "built_at": utc_now(),
    }


def evidence_list(claims: list[dict[str, Any]], excluded: set[str] | None = None) -> list[dict[str, Any]]:
    """Every link and quote, ready for the script writer and the YouTube description."""
    excluded = excluded or set()
    out, seen = [], set()
    for c in claims:
        by_id = {s["source_id"]: s for s in c["sources"]}
        for e in c["excerpts"]:
            s = by_id.get(e["source_id"]) or db.one("SELECT * FROM source WHERE source_id=?", (e["source_id"],)) or {}
            eid = f"E{e['excerpt_id']}"
            if eid in seen:
                continue
            seen.add(eid)
            out.append({"id": eid, "kind": "quote", "claim_id": c["claim_id"], "source_id": e["source_id"],
                        "title": s.get("title"), "publisher": s.get("publisher"), "date": s.get("date"),
                        "url": s.get("url"), "archive_url": s.get("archive_url"), "type": s.get("source_type"),
                        "quote": e["text"], "supports": e.get("supports") or "",
                        "found_by": s.get("found_by") or "database", "include": eid not in excluded})
        for s in c["sources"]:
            if s["source_type"] == "kf_index" or s["source_id"] in seen:
                continue
            seen.add(s["source_id"])
            out.append({"id": s["source_id"], "kind": "link", "claim_id": c["claim_id"], "source_id": s["source_id"],
                        "title": s["title"], "publisher": s.get("publisher"), "date": s.get("date"),
                        "url": s.get("url"), "archive_url": s.get("archive_url"), "type": s["source_type"],
                        "quote": "", "supports": s.get("supports_field") or "",
                        "found_by": s.get("found_by") or "database",
                        "include": bool(s["is_primary"]) and s["source_id"] not in excluded})
    return out


# ---------------------------------------------------------------- agent steps
def _quotes(llm: Ollama, claim: dict[str, Any], title: str, text: str) -> list[dict[str, str]]:
    query = " ".join(str(claim.get(k) or "") for k in ("short_title", "claim_summary", "harm_summary", "who_benefited"))
    passages = sources.relevant_passages(text, query)
    if not passages:
        return []
    answer = llm.chat_json([
        {"role": "system", "content": (
            "You copy sentences out of a document for a fact-checker. Copy them EXACTLY, character for "
            "character. Never paraphrase, never fix typos, never join sentences from different places. "
            "Only copy sentences that state facts about the claim (dates, court findings, what really "
            "happened, who made money, who was harmed). If nothing is relevant, return an empty list.")},
        {"role": "user", "content": f"Claim being checked: {claim['short_title']}\n"
                                    f"Summary: {claim.get('claim_summary') or ''}\n\nDocument ({title}):\n<<<\n"
                                    f"{passages}\n>>>\n\nCopy up to 2 sentences, and say in a few words what each shows."},
    ], EXCERPT_SCHEMA, temperature=0.1)
    return [x for x in answer.get("excerpts", [])[:2] if len((x.get("quote") or "").strip()) >= 20]


def _read(url: str) -> dict[str, Any]:
    page = web.fetch(url)
    if not page["ok"] and settings()["research"]["use_wayback"]:
        page = web.fetch_via_wayback(url)
    return page


def _new_source_id(url: str) -> str:
    return "S-WEB-" + hashlib.sha1(url.encode()).hexdigest()[:10].upper()


def _add_found_source(claim_id: str, hit: dict[str, Any], page: dict[str, Any], question: str) -> str:
    sid = _new_source_id(hit["url"])
    stype = search.source_type(page.get("final_url") or hit["url"])
    with db.transaction() as con:
        con.execute("""INSERT OR IGNORE INTO source(source_id, title, publisher, date, url, source_type,
                       reliability, notes, found_by) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (sid, (hit.get("title") or search.domain(hit["url"]))[:300], search.domain(hit["url"]),
                     hit.get("date"), hit["url"], stype, "medium" if stype != "other" else "low",
                     f"Found by the research agent ({hit['finder']}) searching: {question}", "agent"))
        con.execute("""UPDATE source SET local_copy_path=?, text_path=?, accessed_at=?, http_status=?,
                       archive_url=COALESCE(archive_url, ?) WHERE source_id=?""",
                    (page.get("path"), None, utc_now(), page.get("status"), page.get("archive_url"), sid))
        con.execute("INSERT OR IGNORE INTO claim_source VALUES (?,?,?,?)",
                    (claim_id, sid, "agent", f"search: {question}"))
    # point the source at the saved text so quotes can be checked against it
    row = db.one("SELECT text_path FROM web_cache WHERE url=?", (hit["url"],))
    if row and row["text_path"]:
        db.execute("UPDATE source SET text_path=? WHERE source_id=?", (row["text_path"], sid))
    return sid


def run(ctx: Context) -> None:
    ep = ctx.episode
    if not ep.claim_ids:
        raise StageError("This episode has no claims. Pick a story on the Database page.")
    llm = Ollama()
    cfg = settings()["research"]
    n_queries, n_pages = DEPTH.get(ctx.options.get("depth") or cfg["depth"], DEPTH["normal"])
    packet = build_packet(ep)
    claims = packet["claims"]
    kept = rejected = found = 0

    # 1. sources already in the database
    known = [s for c in claims for s in c["sources"] if s["is_primary"] and s.get("url")]
    for n, s in enumerate({s["source_id"]: s for s in known}.values()):
        ctx.check_cancel()
        ctx.progress(f"Reading sources on file: {s['source_id']} ({n + 1}/{len(known)})", 2 + 18 * n / max(1, len(known)))
        if s.get("text_path"):
            continue
        result = sources.fetch_source(s["source_id"], refresh=ctx.options.get("refresh", False))
        if not result["ok"] and cfg["use_wayback"]:
            page = web.fetch_via_wayback(s["url"])
            if page["ok"]:
                row = db.one("SELECT text_path FROM web_cache WHERE url=?", (s["url"],))
                db.execute("UPDATE source SET text_path=?, archive_url=?, accessed_at=? WHERE source_id=?",
                           (row["text_path"] if row else None, page.get("archive_url"), utc_now(), s["source_id"]))
                ctx.log(f"  {s['source_id']}: page gone, used the Wayback Machine copy")
            else:
                ctx.log(f"  {s['source_id']}: couldn't read ({result.get('error')})")
    packet = build_packet(ep)
    claims = packet["claims"]
    for n, c in enumerate(claims):
        for s in c["sources"]:
            ctx.check_cancel()
            if not s["is_primary"] or s["source_id"] in {e["source_id"] for e in c["excerpts"]}:
                continue
            text = sources.source_text(s["source_id"])
            if not text:
                continue
            ctx.progress(f"Finding quotes for {c['claim_id']} in {s['source_id']}", 20 + 10 * n / max(1, len(claims)))
            for q in _quotes(llm, c, s["title"], text):
                eid, ok = sources.add_excerpt(s["source_id"], q["quote"].strip(), c["claim_id"])
                db.execute("UPDATE source_excerpt SET supports=? WHERE excerpt_id=?", (q.get("supports"), eid))
                kept, rejected = kept + ok, rejected + (not ok)

    # 2. the agents go looking for more
    if not ctx.options.get("database_only"):
        for n, c in enumerate(claims):
            ctx.check_cancel()
            base = 30 + 55 * n / max(1, len(claims))
            step = 55 / max(1, len(claims))
            ctx.progress(f"Planning searches for {c['claim_id']} ({n + 1}/{len(claims)})", base)
            plan = llm.chat_json([
                {"role": "system", "content": (
                    "You plan web searches for a fact-checker looking for PRIMARY evidence: court records, "
                    "government documents, wire reports, archived news from the time, academic studies. "
                    "Write short search queries (3 to 8 words) that would find documents showing what really "
                    "happened, who promoted the claim and profited, and what harm it caused. No questions, "
                    "no quotation marks.")},
                {"role": "user", "content": f"Claim: {c['short_title']}\nSummary: {c.get('claim_summary') or ''}\n"
                                            f"Year: {c.get('first_known_year') or ''}\nPeople: "
                                            f"{', '.join(p['name'] for p in c['people'][:6])}\n"
                                            f"Write {n_queries} queries."},
            ], QUERY_SCHEMA, temperature=0.4)
            queries = [q.strip() for q in plan.get("queries", []) if q.strip()][:n_queries]
            have = {s.get("url") for s in c["sources"]}
            candidates: list[tuple[dict[str, Any], str]] = []
            for k, q in enumerate(queries):
                ctx.check_cancel()
                ctx.progress(f"Searching: \"{q}\" ({k + 1}/{len(queries)} for {c['claim_id']})", base + step * 0.3 * k / max(1, len(queries)))
                for hit in search.search_all(q):
                    if hit.get("map_only") or hit["url"] in have or any(hit["url"] == h["url"] for h, _ in candidates):
                        continue
                    candidates.append((hit, q))
            candidates.sort(key=lambda hq: search.rank(hq[0]))
            read = 0
            for hit, q in candidates:
                if read >= n_pages:
                    break
                ctx.check_cancel()
                ctx.progress(f"Reading {search.domain(hit['url'])} for {c['claim_id']}",
                             base + step * (0.3 + 0.7 * read / max(1, n_pages)))
                page = _read(hit["url"])
                if not page.get("ok"):
                    continue
                read += 1
                quotes = _quotes(llm, c, hit.get("title", ""), page["text"])
                good = [x for x in quotes if sources.quote_in_text(x["quote"], page["text"])]
                rejected += len(quotes) - len(good)
                if not good:
                    continue
                sid = _add_found_source(c["claim_id"], hit, page, q)
                found += 1
                for x in good:
                    eid, ok = sources.add_excerpt(sid, x["quote"].strip(), c["claim_id"])
                    db.execute("UPDATE source_excerpt SET supports=? WHERE excerpt_id=?", (x.get("supports"), eid))
                    kept += ok

    # 3. make every link permanent
    packet = build_packet(ep)
    if cfg["use_wayback"]:
        todo = [e for e in packet["evidence"] if e.get("url") and not e.get("archive_url")]
        todo = list({e["source_id"]: e for e in todo}.values())
        for n, e in enumerate(todo):
            ctx.check_cancel()
            ctx.progress(f"Getting a permanent Wayback copy of {search.domain(e['url'])} ({n + 1}/{len(todo)})",
                         85 + 14 * n / max(1, len(todo)))
            snap = web.save_page_now(e["url"]) if cfg["archive_new_links"] else web.wayback_closest(e["url"])
            if snap:
                db.execute("UPDATE source SET archive_url=? WHERE source_id=?", (snap, e["source_id"]))
        packet = build_packet(ep)

    write_json(ep.path("research.json"), packet)
    write_text(ep.path("research.md"), render_markdown(packet))
    ctx.log(f"Research done: {found} new sources found, {kept} quotes kept, {rejected} thrown out "
            "because they weren't word for word in the page.")
    ctx.progress(f"Done: {len(packet['evidence'])} pieces of evidence. Look them over.", 100)


def set_include(ep: Episode, evidence_id: str, include: bool) -> None:
    packet = read_json(ep.path("research.json"))
    for e in packet.get("evidence", []):
        if e["id"] == evidence_id:
            e["include"] = include
    write_json(ep.path("research.json"), packet)


def render_markdown(packet: dict[str, Any]) -> str:
    lines = [f"# Research: {packet['title']}", ""]
    if packet["restrictions"]:
        lines += ["## Careful-topic rules", ""] + [f"- **{r['rule']}** ({r['subject_id']}): {r.get('note') or ''}"
                                                   for r in packet["restrictions"]] + [""]
    for c in packet["claims"]:
        lines += [f"## {c['claim_id']}: {c['short_title']} ({c['falsity_status']})", ""]
        for e in [x for x in packet["evidence"] if x["claim_id"] == c["claim_id"]]:
            link = e.get("url") or ""
            arch = f" (archived: {e['archive_url']})" if e.get("archive_url") else ""
            if e["kind"] == "quote":
                lines.append(f"- {e['id']} [{e['type']}] \"{e['quote']}\" - {e.get('title')}, {link}{arch}")
            else:
                lines.append(f"- {e['id']} [{e['type']}] {e.get('title')} {link}{arch}")
        lines.append("")
    return "\n".join(lines)


def check(ep: Episode) -> list[Check]:
    packet = read_json(ep.path("research.json"))
    if not packet:
        return [Check(BLOCK, "No research yet. Press Start research.")]
    out: list[Check] = []
    if not packet["claims"]:
        out.append(Check(BLOCK, "The episode has no claims."))
    rules = {(r["subject_type"], r["subject_id"], r["rule"]) for r in packet["restrictions"]}
    for c in packet["claims"]:
        prim = [s for s in c["sources"] if s["is_primary"]]
        if not prim:
            out.append(Check(BLOCK, f"{c['claim_id']} ({c['short_title'][:40]}) still has no primary source. "
                                    "Run research again (deeper), or leave this claim out on the Database page."))
        courts = any(r[2] == "courts_only" and (r[1] == c["claim_id"] or r[1] == c.get("arc_id")
                                                 or r[1] == (packet.get("arc") or {}).get("arc_id")) for r in rules)
        if courts and not any(s["source_type"] in ("court", "gov") for s in prim):
            out.append(Check(BLOCK, f"{c['claim_id']} is a victims topic: it needs a court or government source."))
        if c["falsity_status"] in ("unverified", "contested"):
            out.append(Check(WARN, f"{c['claim_id']} is '{c['falsity_status']}': the video must say so plainly."))
    ev = packet.get("evidence", [])
    quotes = sum(1 for e in ev if e["kind"] == "quote")
    agent = sum(1 for e in ev if e.get("found_by") == "agent")
    archived = sum(1 for e in ev if e.get("archive_url"))
    if not quotes:
        out.append(Check(WARN, "No word-for-word quotes yet, so the script will have to paraphrase."))
    for r in packet["restrictions"]:
        out.append(Check(WARN, f"Careful topic: {r['rule']} ({r['subject_id']}). {r.get('note') or ''}"))
    if not any(c.level == BLOCK for c in out):
        out.append(Check(OK, f"{len(ev)} pieces of evidence ({quotes} quotes, {agent} found by the agents, "
                             f"{archived} with permanent Wayback copies)."))
    return out
