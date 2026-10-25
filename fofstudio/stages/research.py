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
5. Every piece of evidence gets a short plain-English summary of what it is and what it shows.
New finds go into the database as new sources, marked "found by the research agent", so the
research is kept: another video on the same subject starts with everything found so far.

Nothing is ticked to begin with. You tick the evidence this video will use; the stories, the
script and the YouTube description only see what you ticked. "Dig deeper" sends the agents
after more on the items you ticked.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .. import db, sources
from ..agents import search, web
from ..config import settings
from ..episode import Episode
from ..llm import Ollama, model_for
from ..util import StageError, read_json, utc_now, write_json, write_text
from .base import BLOCK, OK, WARN, Check, Context

def picks_schema(n: int) -> dict[str, Any]:
    """The AI answers with sentence NUMBERS (only real ones are allowed); the program copies the words."""
    nums = list(range(1, n + 1))
    return {"type": "object", "properties": {"picks": {"type": "array", "maxItems": 2, "items": {
        "type": "object", "properties": {
            "sentence": {"type": "integer", "enum": nums},
            "through": {"type": "integer", "enum": nums},
            "shows": {"type": "string"}},
        "required": ["sentence", "through", "shows"]}}}, "required": ["picks"]}


SENTENCE_END = re.compile(r"(?<=[.!?])([\"”’')\]]*)\s+(?=[\"“‘(\[]?[A-Z0-9])")
ABBREVIATIONS = {"dr", "mr", "mrs", "ms", "st", "jr", "sr", "vs", "no", "gen", "sen", "rep", "gov", "lt", "col",
                 "inc", "co", "corp", "ltd", "prof", "rev", "hon", "u.s", "u.k", "jan", "feb", "mar", "apr", "aug",
                 "sept", "sep", "oct", "nov", "dec", "e.g", "i.e", "etc", "v", "fig", "p", "pp", "approx"}


def numbered_sentences(passages: str, limit: int = 160) -> list[dict[str, Any]]:
    """Split the passages into sentences, remembering where each sits in its paragraph, so a run of
    sentences can be copied out exactly as written."""
    out: list[dict[str, Any]] = []
    for p_no, para in enumerate(x for x in passages.split("\n\n") if x.strip()):
        cuts = []
        for m in SENTENCE_END.finditer(para):
            word = re.search(r"([\w.]+)\.$", para[:m.start()])
            w = (word.group(1) if word else "").lower()
            if w in ("no", "p") and not para[m.end():m.end() + 1].isdigit():
                w = ""                        # "said no. Then..." ends a sentence; "No. 5" doesn't
            if w in ABBREVIATIONS or (len(w) == 1 and w.isalpha()):
                continue                      # "Dr. Smith", "U.S. officials", "John Q. Public"
            cuts.append((m.start() + len(m.group(1)), m.end()))
        cuts.append((len(para), len(para)))
        start = 0
        for seg_end, nxt in cuts:
            raw = para[start:seg_end]
            text = raw.strip()
            if text:
                s0 = start + len(raw) - len(raw.lstrip())
                out.append({"n": len(out) + 1, "para": p_no, "start": s0, "end": s0 + len(text), "text": text,
                            "source": para})
                if len(out) >= limit:
                    return out
            start = nxt
    return out


def copy_sentences(sents: list[dict[str, Any]], first: int, last: int) -> str:
    """The exact words of sentences first..last (up to 3, in one paragraph)."""
    a = sents[first - 1]
    last = max(first, min(last, first + 2, len(sents)))
    b = sents[last - 1]
    if b["para"] != a["para"]:
        b = a
    return a["source"][a["start"]:b["end"]]
SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
}
QUERY_SCHEMA = {
    "type": "object",
    "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
    "required": ["queries"],
}
DEPTH = {"files": (0, 0), "quick": (2, 3), "normal": (4, 5), "deep": (6, 8)}  # searches, pages read, per claim


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
                                 s.summary, s.notes,
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
    ticked = {e["id"] for e in old.get("evidence", []) if e.get("include")}
    return {
        "project_id": ep.project_id, "title": ep.title, "arc": arc,
        "subject": {"kind": proj.get("subject_type") or ("story" if arc else "conspiracy"),
                    "id": proj.get("subject_id") or info.get("arc_id"), "title": ep.title},
        "claims": claims,
        "evidence": evidence_list(claims, ticked, set(old.get("new_ids", []))),
        "restrictions": restrictions_for(claim_ids, info.get("arc_id")),
        "built_at": utc_now(),
        "researched_at": old.get("researched_at"),
        "runs": old.get("runs", []),
        "new_ids": old.get("new_ids", []),
    }


def evidence_list(claims: list[dict[str, Any]], ticked: set[str] | None = None,
                  new_ids: set[str] | None = None) -> list[dict[str, Any]]:
    """Every link and quote. Nothing is ticked unless you ticked it before."""
    ticked, new_ids = ticked or set(), new_ids or set()
    out, seen = [], set()

    def item(**kw: Any) -> dict[str, Any]:
        kw["include"] = kw["id"] in ticked
        kw["new"] = kw["id"] in new_ids
        return kw

    for c in claims:
        by_id = {s["source_id"]: s for s in c["sources"]}
        for e in c["excerpts"]:
            s = by_id.get(e["source_id"]) or db.one("SELECT * FROM source WHERE source_id=?", (e["source_id"],)) or {}
            eid = f"E{e['excerpt_id']}"
            if eid in seen:
                continue
            seen.add(eid)
            out.append(item(id=eid, kind="quote", claim_id=c["claim_id"], claim=c["short_title"],
                            source_id=e["source_id"], excerpt_id=e["excerpt_id"],
                            title=s.get("title"), publisher=s.get("publisher"), date=s.get("date"),
                            url=s.get("url"), archive_url=s.get("archive_url"), type=s.get("source_type"),
                            reliability=s.get("reliability"), quote=e["text"], supports=e.get("supports") or "",
                            summary=_summary_of(s), found_by=s.get("found_by") or "database"))
        for s in c["sources"]:
            if s["source_type"] == "kf_index" or s["source_id"] in seen:
                continue
            seen.add(s["source_id"])
            out.append(item(id=s["source_id"], kind="link", claim_id=c["claim_id"], claim=c["short_title"],
                            source_id=s["source_id"], excerpt_id=None,
                            title=s["title"], publisher=s.get("publisher"), date=s.get("date"),
                            url=s.get("url"), archive_url=s.get("archive_url"), type=s["source_type"],
                            reliability=s.get("reliability"), quote="", supports=s.get("supports_field") or "",
                            summary=_summary_of(s), found_by=s.get("found_by") or "database"))
    return out


def _summary_of(s: dict[str, Any]) -> str:
    """The AI's write-up of the source if there is one, else the database's own notes on it."""
    if s.get("summary"):
        return s["summary"]
    notes = s.get("notes") or ""
    return "" if notes.startswith("Found by the research agent") else notes


def selected(packet: dict[str, Any]) -> dict[str, Any]:
    """The packet cut down to the evidence you ticked: what the stories, script and description use.
    A claim with nothing ticked is left out of the video."""
    chosen = [e for e in packet.get("evidence", []) if e.get("include") and e.get("type") != "kf_index"]
    srcs: dict[str, set[str]] = {}
    quotes: dict[str, set[int]] = {}
    for e in chosen:
        srcs.setdefault(e["claim_id"], set()).add(e["source_id"])
        if e.get("kind") == "quote":  # older research files have no excerpt_id; it's in the "E14" label
            num = e.get("excerpt_id") if e.get("excerpt_id") is not None else str(e["id"]).lstrip("E")
            if str(num).isdigit():
                quotes.setdefault(e["claim_id"], set()).add(int(num))
    by_source = {}
    for e in chosen:
        by_source.setdefault(e["source_id"], e)
    claims = []
    for c in packet.get("claims", []):
        if c["claim_id"] not in srcs:
            continue
        mine = srcs[c["claim_id"]]
        # a source ticked under another claim can still back this one if the database links them
        linked = {s["source_id"] for s in c["sources"]}
        mine = mine | ({sid for sid in by_source if sid in linked})
        sources_ = [dict(s, summary=by_source[s["source_id"]].get("summary") or "")
                    for s in c["sources"] if s["source_id"] in mine and s["source_type"] != "kf_index"]
        known = {s["source_id"] for s in sources_}
        for sid in mine - known:  # ticked under this claim but not linked in the database
            e = by_source[sid]
            sources_.append({"source_id": sid, "title": e.get("title"), "publisher": e.get("publisher"),
                             "date": e.get("date"), "url": e.get("url"), "source_type": e.get("type"),
                             "is_primary": e.get("type") in PRIMARY_TYPES, "summary": e.get("summary") or ""})
        ticked_quotes = {q for k, v in quotes.items() for q in v}
        excerpts = [x for x in c["excerpts"] if int(x["excerpt_id"]) in ticked_quotes]
        claims.append({**c, "sources": sources_, "excerpts": excerpts})
    return {**packet, "claims": claims, "evidence": chosen}


PRIMARY_TYPES = {"court", "wire", "gov", "journalism", "archive_audio", "academic", "museum"}


def prepare(ep: Episode) -> dict[str, Any]:
    """Show what's already on file without running the agents (fast; no internet)."""
    packet = build_packet(ep)
    write_json(ep.path("research.json"), packet)
    return packet


# ---------------------------------------------------------------- agent steps
def _quotes(llm: Ollama, claim: dict[str, Any], title: str, text: str) -> list[dict[str, str]]:
    query = " ".join(str(claim.get(k) or "") for k in ("short_title", "claim_summary", "harm_summary", "who_benefited"))
    passages = sources.relevant_passages(text, query)
    if not passages:
        return []
    sents = [s for s in numbered_sentences(passages) if len(s["text"]) >= 12]
    if not sents:
        return []
    for k, s in enumerate(sents, 1):
        s["n"] = k
    listing = "\n".join(f"[{s['n']}] {s['text'][:700]}" for s in sents)
    answer = llm.chat_json([
        {"role": "system", "content": (
            "You pick sentences out of a document for a fact-checker. The document is split into numbered "
            "sentences. Answer with sentence NUMBERS only: the program copies the exact words, so never write "
            "the sentence yourself. Pick only sentences that state facts about the claim (dates, court findings, "
            "what really happened, who made money, who was harmed). 'through' is the last sentence of a run "
            "(the same number for one sentence; at most 2 more in a row). If nothing is relevant, return an "
            "empty list.")},
        {"role": "user", "content": f"Claim being checked: {claim['short_title']}\n"
                                    f"Summary: {claim.get('claim_summary') or ''}\n\nDocument ({title}), "
                                    f"numbered sentences:\n{listing}\n\nPick up to 2, and say in a few words "
                                    "what each shows."},
    ], picks_schema(len(sents)), model=model_for("research_quotes"), temperature=0.1)
    out = []
    for p in answer.get("picks", [])[:2]:
        first = int(p.get("sentence") or 0)
        if not 1 <= first <= len(sents):
            continue
        quote = copy_sentences(sents, first, int(p.get("through") or first))
        if len(quote.strip()) >= 20:
            out.append({"quote": quote, "supports": p.get("shows", "")})
    return out


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


def _summarize(llm: Ollama, claim: dict[str, Any], title: str, text: str) -> str:
    query = " ".join(str(claim.get(k) or "") for k in ("short_title", "claim_summary"))
    passages = sources.relevant_passages(text, query) or text[:4000]
    answer = llm.chat_json([
        {"role": "system", "content": (
            "You write short notes for a fact-checker about one document. In 2 to 4 plain sentences say: "
            "what this document is (who made it, when, what kind), and what it shows about the claim. "
            "Only say what the document itself says. If it doesn't really bear on the claim, say so. "
            "No opinions, no guesses, no outside facts.")},
        {"role": "user", "content": f"Claim being checked: {claim['short_title']}\n"
                                    f"Document title: {title}\n<<<\n{passages[:6000]}\n>>>"},
    ], SUMMARY_SCHEMA, model=model_for("research_summary"), temperature=0.2)
    return (answer.get("summary") or "").strip()


def _hunt(ctx: Context, llm: Ollama, claim: dict[str, Any], about: str, n_queries: int, n_pages: int,
          base: float, step: float, label: str) -> tuple[int, int, int]:
    """Plan searches, search, read the best pages, keep word-for-word quotes. Returns (found, kept, rejected)."""
    found = kept = rejected = 0
    ctx.progress(f"Planning searches for {label}", base)
    plan = llm.chat_json([
        {"role": "system", "content": (
            "You plan web searches for a fact-checker looking for PRIMARY evidence: court records, "
            "government documents, wire reports, archived news from the time, academic studies. "
            "Write short search queries (3 to 8 words) that would find documents showing what really "
            "happened, who promoted the claim and profited, and what harm it caused. No questions, "
            "no quotation marks.")},
        {"role": "user", "content": f"{about}\nWrite {n_queries} queries."},
    ], QUERY_SCHEMA, model=model_for("research_plan"), temperature=0.4)
    queries = [q.strip() for q in plan.get("queries", []) if q.strip()][:n_queries]
    have = {s.get("url") for s in claim["sources"]}
    candidates: list[tuple[dict[str, Any], str]] = []
    for k, q in enumerate(queries):
        ctx.check_cancel()
        ctx.progress(f"Searching: \"{q}\" ({k + 1}/{len(queries)} for {label})",
                     base + step * 0.3 * k / max(1, len(queries)))
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
        ctx.progress(f"Reading {search.domain(hit['url'])} for {label}",
                     base + step * (0.3 + 0.7 * read / max(1, n_pages)))
        page = _read(hit["url"])
        if not page.get("ok"):
            continue
        read += 1
        quotes = _quotes(llm, claim, hit.get("title", ""), page["text"])
        good = [x for x in quotes if sources.quote_in_text(x["quote"], page["text"])]
        rejected += len(quotes) - len(good)
        if not good:
            continue
        sid = _add_found_source(claim["claim_id"], hit, page, q)
        found += 1
        for x in good:
            eid, ok = sources.add_excerpt(sid, x["quote"].strip(), claim["claim_id"])
            db.execute("UPDATE source_excerpt SET supports=? WHERE excerpt_id=?", (x.get("supports"), eid))
            kept += ok
    return found, kept, rejected


def run(ctx: Context) -> None:
    ep = ctx.episode
    if not ep.claim_ids:
        raise StageError("This episode has no claims. Pick a story on the Database page.")
    llm = Ollama()
    cfg = settings()["research"]
    depth = ctx.options.get("depth") or cfg["depth"]
    n_queries, n_pages = DEPTH.get(depth, DEPTH["normal"])
    focus = list(ctx.options.get("focus") or [])
    before = read_json(ep.path("research.json")) or {}
    packet = build_packet(ep)
    before_ids = {e["id"] for e in packet["evidence"]}
    claims = packet["claims"]
    kept = rejected = found = 0

    if not focus:
        # 1. sources already in the database
        known = list({s["source_id"]: s for c in claims for s in c["sources"]
                      if s["is_primary"] and s.get("url")}.values())
        for n, s in enumerate(known):
            ctx.check_cancel()
            ctx.progress(f"Reading sources on file: {s['source_id']} ({n + 1}/{len(known)})", 2 + 13 * n / max(1, len(known)))
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
                ctx.progress(f"Finding quotes for {c['claim_id']} in {s['source_id']}", 15 + 10 * n / max(1, len(claims)))
                for q in _quotes(llm, c, s["title"], text):
                    eid, ok = sources.add_excerpt(s["source_id"], q["quote"].strip(), c["claim_id"])
                    db.execute("UPDATE source_excerpt SET supports=? WHERE excerpt_id=?", (q.get("supports"), eid))
                    kept, rejected = kept + ok, rejected + (not ok)

        # 2. the agents go looking for more, claim by claim
        if n_queries and not ctx.options.get("database_only"):
            for n, c in enumerate(claims):
                ctx.check_cancel()
                about = (f"Claim: {c['short_title']}\nSummary: {c.get('claim_summary') or ''}\n"
                         f"Year: {c.get('first_known_year') or ''}\nPeople: "
                         f"{', '.join(p['name'] for p in c['people'][:6])}")
                f, k, r = _hunt(ctx, llm, c, about, n_queries, n_pages, 25 + 50 * n / max(1, len(claims)),
                                50 / max(1, len(claims)), f"{c['claim_id']} ({n + 1}/{len(claims)})")
                found, kept, rejected = found + f, kept + k, rejected + r
    else:
        # dig deeper: the agents chase each piece of evidence you ticked
        items = [e for e in packet["evidence"] if e["id"] in focus]
        if not items:
            raise StageError("Tick the evidence you want the agents to dig into, then press Dig deeper.")
        by_claim = {c["claim_id"]: c for c in claims}
        n_queries, n_pages = max(n_queries, 3), max(n_pages, 3)
        for n, e in enumerate(items):
            ctx.check_cancel()
            c = by_claim[e["claim_id"]]
            about = (f"Claim: {c['short_title']}\nDig deeper into this piece of evidence and find more "
                     f"documents about the same thing:\nTitle: {e.get('title') or ''}\n"
                     f"Date: {e.get('date') or ''}\nWhat it shows: {e.get('summary') or e.get('supports') or ''}\n"
                     + (f"Quote: {e['quote']}\n" if e.get("quote") else "")
                     + (f"Producer's note: {ctx.options['notes']}\n" if ctx.options.get("notes") else ""))
            f, k, r = _hunt(ctx, llm, c, about, n_queries, n_pages, 5 + 70 * n / len(items), 70 / len(items),
                            f"{e['id']} ({n + 1}/{len(items)})")
            found, kept, rejected = found + f, kept + k, rejected + r

    # 3. a short write-up of what each source is and what it shows
    packet = build_packet(ep)
    claim_by_id = {c["claim_id"]: c for c in packet["claims"]}
    done = {r["source_id"] for r in db.rows("SELECT source_id FROM source WHERE summary IS NOT NULL AND summary != ''")}
    todo = [e for e in {e["source_id"]: e for e in packet["evidence"]}.values() if e["source_id"] not in done]
    for n, e in enumerate(todo):
        ctx.check_cancel()
        text = sources.source_text(e["source_id"])
        if not text:
            continue
        ctx.progress(f"Writing a summary of {e.get('title') or e['source_id']} ({n + 1}/{len(todo)})",
                     75 + 10 * n / max(1, len(todo)))
        summary = _summarize(llm, claim_by_id[e["claim_id"]], e.get("title") or "", text)
        if summary:
            db.execute("UPDATE source SET summary=? WHERE source_id=?", (summary, e["source_id"]))

    # 4. make every link permanent
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

    # keep your ticks, flag what's new, and remember this run
    packet = build_packet(ep)
    new_ids = [e["id"] for e in packet["evidence"] if e["id"] not in before_ids]
    for e in packet["evidence"]:
        e["new"] = e["id"] in new_ids
        if e["id"] in focus:
            e["include"] = True
    packet["new_ids"] = new_ids
    packet["researched_at"] = utc_now()
    packet["runs"] = (before.get("runs") or []) + [{
        "at": packet["researched_at"], "depth": depth, "focus": focus, "found_sources": found,
        "quotes_kept": kept, "quotes_thrown_out": rejected, "new_evidence": len(new_ids)}]
    write_json(ep.path("research.json"), packet)
    write_text(ep.path("research.md"), render_markdown(packet))
    ctx.log(f"Research done: {found} new sources found, {kept} quotes kept, {rejected} thrown out "
            "because they weren't word for word in the page. Everything is saved in the database.")
    ctx.progress(f"Done: {len(new_ids)} new pieces of evidence, {len(packet['evidence'])} in all. Tick the ones to use.", 100)


def set_include(ep: Episode, evidence_ids: str | list[str], include: bool) -> None:
    ids = {evidence_ids} if isinstance(evidence_ids, str) else set(evidence_ids)
    packet = read_json(ep.path("research.json"))
    for e in packet.get("evidence", []):
        if e["id"] in ids:
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
            tick = "[x]" if e.get("include") else "[ ]"
            if e["kind"] == "quote":
                lines.append(f"- {tick} {e['id']} [{e['type']}] \"{e['quote']}\" - {e.get('title')}, {link}{arch}")
            else:
                lines.append(f"- {tick} {e['id']} [{e['type']}] {e.get('title')} {link}{arch}")
            if e.get("summary"):
                lines.append(f"  {e['summary']}")
        lines.append("")
    return "\n".join(lines)


def check(ep: Episode) -> list[Check]:
    packet = read_json(ep.path("research.json"))
    if not packet:
        return [Check(BLOCK, "No research yet. Choose how deep, then press Start research.")]
    out: list[Check] = []
    if not packet["claims"]:
        out.append(Check(BLOCK, "The episode has no claims."))
    ev = packet.get("evidence", [])
    ticked = [e for e in ev if e.get("include") and e.get("type") != "kf_index"]
    if not ticked:
        return out + [Check(BLOCK, f"Nothing is ticked yet. Tick the evidence this video will use "
                                   f"({len(ev)} pieces on file).")]
    rules = {(r["subject_type"], r["subject_id"], r["rule"]) for r in packet["restrictions"]}
    used = 0
    for c in packet["claims"]:
        mine = [e for e in ticked if e["claim_id"] == c["claim_id"]]
        if not mine:
            out.append(Check(WARN, f"{c['claim_id']} ({c['short_title'][:40]}): nothing ticked, so this video "
                                   "leaves it out."))
            continue
        used += 1
        if not any(e.get("type") in PRIMARY_TYPES for e in mine):
            out.append(Check(BLOCK, f"{c['claim_id']} ({c['short_title'][:40]}): tick at least one primary source "
                                    "(court, government, news, academic...) for it, or untick it entirely."))
        courts = any(r[2] == "courts_only" and (r[1] == c["claim_id"] or r[1] == c.get("arc_id")
                                                 or r[1] == (packet.get("arc") or {}).get("arc_id")) for r in rules)
        if courts and not any(e.get("type") in ("court", "gov") for e in mine):
            out.append(Check(BLOCK, f"{c['claim_id']} is a victims topic: tick a court or government source for it."))
        if c["falsity_status"] in ("unverified", "contested"):
            out.append(Check(WARN, f"{c['claim_id']} is '{c['falsity_status']}': the video must say so plainly."))
    quotes = sum(1 for e in ticked if e["kind"] == "quote")
    if not quotes:
        out.append(Check(WARN, "No word-for-word quotes ticked, so the script will have to paraphrase."))
    for r in packet["restrictions"]:
        out.append(Check(WARN, f"Careful topic: {r['rule']} ({r['subject_id']}). {r.get('note') or ''}"))
    if not any(c.level == BLOCK for c in out):
        out.append(Check(OK, f"{len(ticked)} of {len(ev)} pieces of evidence ticked ({quotes} quotes), "
                             f"covering {used} of {len(packet['claims'])} claims."))
    return out
