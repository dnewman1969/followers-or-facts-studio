"""What an episode can be about: a Story (arc), a Conspiracy (single claim), a Person or an
Organization. Lists for the Database page, a plain-English breakdown of what the video
will cover, and the claims that go to Research when you press OK."""

from __future__ import annotations

from typing import Any

from . import db

KINDS = {
    "story": "Stories",
    "conspiracy": "Conspiracies",
    "person": "People",
    "org": "Organizations",
}
MAX_CLAIMS = 8


def listing(kind: str, search: str = "") -> list[dict[str, Any]]:
    q = f"%{search.strip()}%"
    if kind == "story":
        return db.rows("""SELECT a.arc_id AS id, a.title, a.status, s.claims, s.sourced_claims AS sourced,
                                 s.careful FROM arc a JOIN arc_strength s USING(arc_id)
                          WHERE a.title LIKE ? OR a.arc_id LIKE ? OR a.notes LIKE ?
                          ORDER BY s.sourced_claims DESC, s.claims DESC""", (q, q, q))
    if kind == "conspiracy":
        return db.rows("""SELECT c.claim_id AS id, c.short_title AS title, c.falsity_status AS status,
                                 1 AS claims, (r.primary_sources > 0) AS sourced, r.careful,
                                 r.primary_sources
                          FROM claim c JOIN claim_readiness r USING(claim_id)
                          WHERE c.short_title LIKE ? OR c.claim_summary LIKE ? OR c.claim_id LIKE ?
                          ORDER BY r.primary_sources DESC, c.claim_id""", (q, q, q))
    if kind == "person":
        return db.rows("""SELECT p.person_id AS id, p.name AS title, p.role_types AS status,
                                 COUNT(DISTINCT ce.claim_id) AS claims,
                                 COUNT(DISTINCT CASE WHEN r.primary_sources > 0 THEN ce.claim_id END) AS sourced,
                                 0 AS careful
                          FROM person p LEFT JOIN claim_entity ce ON ce.entity_type='person' AND ce.entity_id=p.person_id
                          LEFT JOIN claim_readiness r ON r.claim_id = ce.claim_id
                          WHERE p.name LIKE ? OR p.aka LIKE ? OR p.role_types LIKE ?
                          GROUP BY p.person_id HAVING claims > 0
                          ORDER BY sourced DESC, claims DESC""", (q, q, q))
    if kind == "org":
        return db.rows("""SELECT o.org_id AS id, o.name AS title, o.type AS status,
                                 COUNT(DISTINCT ce.claim_id) AS claims,
                                 COUNT(DISTINCT CASE WHEN r.primary_sources > 0 THEN ce.claim_id END) AS sourced,
                                 0 AS careful
                          FROM organization o LEFT JOIN claim_entity ce ON ce.entity_type='org' AND ce.entity_id=o.org_id
                          LEFT JOIN claim_readiness r ON r.claim_id = ce.claim_id
                          WHERE o.name LIKE ? OR o.role LIKE ?
                          GROUP BY o.org_id HAVING claims > 0
                          ORDER BY sourced DESC, claims DESC""", (q, q))
    raise ValueError(f"Unknown kind {kind}")


def claim_ids_for(kind: str, subject_id: str) -> list[str]:
    if kind == "story":
        sql = "SELECT claim_id FROM claim_readiness WHERE arc_id=? ORDER BY primary_sources DESC, claim_id"
    elif kind == "conspiracy":
        return [subject_id]
    else:
        etype = "person" if kind == "person" else "org"
        sql = (f"SELECT r.claim_id FROM claim_entity ce JOIN claim_readiness r USING(claim_id) "
               f"WHERE ce.entity_type='{etype}' AND ce.entity_id=? GROUP BY r.claim_id "
               f"ORDER BY r.primary_sources DESC, r.claim_id")
    return [r["claim_id"] for r in db.rows(sql, (subject_id,))][:MAX_CLAIMS]


def headline(kind: str, subject_id: str) -> dict[str, Any]:
    if kind == "story":
        r = db.one("SELECT title, notes, harm_documented, first_known_origin FROM arc WHERE arc_id=?", (subject_id,))
        return {"title": r["title"], "about": r["notes"] or "", "harm": r["harm_documented"] or "",
                "origin": r["first_known_origin"] or ""}
    if kind == "conspiracy":
        r = db.one("SELECT short_title, claim_summary, harm_summary, first_known_year FROM claim WHERE claim_id=?",
                   (subject_id,))
        return {"title": r["short_title"], "about": r["claim_summary"] or "", "harm": r["harm_summary"] or "",
                "origin": r["first_known_year"] or ""}
    if kind == "person":
        r = db.one("SELECT name, role_types, motive_notes FROM person WHERE person_id=?", (subject_id,))
        return {"title": r["name"], "about": r["role_types"] or "", "harm": r["motive_notes"] or "", "origin": ""}
    r = db.one("SELECT name, role, tactics FROM organization WHERE org_id=?", (subject_id,))
    return {"title": r["name"], "about": r["role"] or "", "harm": r["tactics"] or "", "origin": ""}


def breakdown(kind: str, subject_id: str) -> dict[str, Any]:
    """Everything the video would talk about, for the Database page's preview pane."""
    claim_ids = claim_ids_for(kind, subject_id)
    head = headline(kind, subject_id)
    claims = []
    people: dict[str, str] = {}
    orgs: dict[str, str] = {}
    sources = 0
    kf: set[str] = set()
    for cid in claim_ids:
        c = db.one("SELECT * FROM claim_readiness r JOIN claim c USING(claim_id) WHERE claim_id=?", (cid,))
        if not c:
            continue
        claims.append(c)
        sources += c["primary_sources"]
        for p in db.rows("""SELECT p.name, ce.link_role FROM claim_entity ce JOIN person p
                            ON p.person_id=ce.entity_id WHERE ce.claim_id=? AND ce.entity_type='person'""", (cid,)):
            people.setdefault(p["name"], p["link_role"])
        for o in db.rows("""SELECT o.name, ce.link_role FROM claim_entity ce JOIN organization o
                            ON o.org_id=ce.entity_id WHERE ce.claim_id=? AND ce.entity_type='org'""", (cid,)):
            orgs.setdefault(o["name"], o["link_role"])
        kf |= {r["kf_ep"] for r in db.rows("SELECT kf_ep FROM kf_episode_link WHERE entity_type='claim' "
                                           "AND entity_id=?", (cid,))}
    arcs = {c["arc_id"] for c in claims if c["arc_id"]}
    rules = []
    for a in arcs | ({subject_id} if kind == "story" else set()):
        rules += db.rows("SELECT rule, note FROM content_restriction WHERE subject_type='arc' AND subject_id=?", (a,))
    for cid in claim_ids:
        rules += db.rows("SELECT rule, note FROM content_restriction WHERE subject_type='claim' AND subject_id=?", (cid,))
    ready = sum(1 for c in claims if c["primary_sources"] > 0)
    return {
        "kind": kind, "id": subject_id, **head,
        "claims": claims, "claim_ids": [c["claim_id"] for c in claims],
        "people": people, "orgs": orgs, "primary_sources": sources,
        "kf_episodes": sorted(kf, key=lambda k: (len(k), k)),
        "rules": {r["rule"]: r["note"] for r in rules},
        "ready": ready, "unsourced": len(claims) - ready,
    }


def breakdown_html(b: dict[str, Any]) -> str:
    import html
    e = html.escape
    parts = [f"<h2 style='margin:0'>{e(b['title'])}</h2>"]
    if b["about"]:
        parts.append(f"<p>{e(b['about'])}</p>")
    status = ("<span style='color:#27ae60'>Ready to research</span>" if b["claims"] and not b["unsourced"]
              else f"<span style='color:#d4a017'>{b['unsourced']} of {len(b['claims'])} claims still need a "
                   "primary source; Research will look for them</span>" if b["claims"]
              else "<span style='color:#c0392b'>No claims linked yet</span>")
    parts.append(f"<p><b>{len(b['claims'])} claims · {b['primary_sources']} primary sources · "
                 f"{len(b['kf_episodes'])} Knowledge Fight episodes.</b> {status}</p>")
    if b["rules"]:
        notes = list(dict.fromkeys(n or r for r, n in b["rules"].items()))
        parts.append("<p style='color:#e67e22'><b>Careful topic:</b> " + "; ".join(e(n) for n in notes) +
                     f" <span style='color:#8a8fa3'>({', '.join(b['rules'])})</span></p>")
    parts.append("<h3>What the video will cover</h3><ol>")
    for c in b["claims"]:
        verdict = {"false": "False", "misleading": "Misleading", "contested": "Contested",
                   "partially_true_wrapped": "A true bit wrapped in a lie",
                   "unverified": "Unverified"}.get(c["falsity_status"], c["falsity_status"])
        parts.append(f"<li><b>{e(c['short_title'])}</b> <span style='color:#8a8fa3'>({verdict}, "
                     f"{c['primary_sources']} primary sources)</span>")
        if c.get("claim_summary"):
            parts.append(f"<br><i>The claim:</i> {e(c['claim_summary'][:400])}")
        if c.get("who_benefited"):
            parts.append(f"<br><i>Who benefited:</i> {e(c['who_benefited'][:300])}")
        if c.get("harm_summary"):
            parts.append(f"<br><i>What it did to people:</i> {e(c['harm_summary'][:300])}")
        parts.append("</li>")
    parts.append("</ol>")
    if b["people"]:
        parts.append("<p><b>People:</b> " + ", ".join(f"{e(n)} ({e(r)})" for n, r in list(b["people"].items())[:15]) + "</p>")
    if b["orgs"]:
        parts.append("<p><b>Organizations:</b> " + ", ".join(e(n) for n in list(b["orgs"])[:15]) + "</p>")
    if b["kf_episodes"]:
        parts.append("<p style='color:#8a8fa3'>Knowledge Fight episodes used as a research map: " +
                     ", ".join("#" + k for k in b["kf_episodes"][:20]) + "</p>")
    return "".join(parts)
