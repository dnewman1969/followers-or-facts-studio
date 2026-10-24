"""Add something new to research: a topic (story), a conspiracy claim, a person or a group.

Everything in the database hangs off claims (what was said), so each new entry gets at least one claim:
  * a topic           -> a new story (arc) with its first claim;
  * a conspiracy      -> a new claim;
  * a person / group  -> the person or group, plus the claim they're known for, linked as "said_it".
New claims start as "unverified" with no sources; the Research step then searches the web and court
records for evidence, and you tick what's good. Nothing is ever marked false until the evidence says so.
"""

from __future__ import annotations

import re
from typing import Any

from . import db
from .util import StageError

KINDS = {"story": "Topic (a story)", "conspiracy": "Conspiracy or claim", "person": "Person", "org": "Group or organization"}


def _slug(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text.upper())
    return "-".join(words[:4])[:32] or "NEW"


def _new_id(prefix: str, table: str, column: str, text: str) -> str:
    base = f"{prefix}-NEW-{_slug(text)}"
    candidate, n = base, 2
    while db.one(f"SELECT 1 FROM {table} WHERE {column}=?", (candidate,)):
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _find(table: str, id_col: str, name: str) -> str | None:
    r = db.one(f"SELECT {id_col} AS id FROM {table} WHERE lower(name)=lower(?)", (name.strip(),))
    return r["id"] if r else None


def _claim(title: str, summary: str, year: str, arc_id: str | None) -> str:
    cid = _new_id("C", "claim", "claim_id", title)
    db.execute("""INSERT INTO claim (claim_id, short_title, claim_summary, first_known_year, arc_id, falsity_status,
                                     status) VALUES (?,?,?,?,?, 'unverified', 'seed')""",
               (cid, title.strip()[:200], summary.strip(), year.strip(), arc_id))
    return cid


def _link_people(claim_id: str, names: str) -> list[str]:
    """Link the named people (existing ones by name, new ones added) to the claim as people who said it."""
    linked = []
    for name in [n.strip() for n in re.split(r"[,;\n]", names or "") if n.strip()]:
        pid = _find("person", "person_id", name)
        if not pid:
            pid = _new_id("P", "person", "person_id", name)
            db.execute("INSERT INTO person (person_id, name, role_types, notes) VALUES (?,?,?,?)",
                       (pid, name, "said_it", "added in the Studio"))
        db.execute("INSERT OR IGNORE INTO claim_entity (claim_id, entity_type, entity_id, link_role) VALUES (?,?,?,?)",
                   (claim_id, "person", pid, "said_it"))
        linked.append(pid)
    return linked


def add(kind: str, name: str, about: str = "", claim: str = "", year: str = "", people: str = "",
        careful: bool = False) -> dict[str, Any]:
    """Add a new subject; returns {"kind", "id", "claim_id"} so the Database page can select it."""
    name, about, claim = name.strip(), about.strip(), claim.strip()
    if len(name) < 3:
        raise StageError("Give it a name (at least a few letters).")
    if kind not in KINDS:
        raise StageError(f"Unknown kind {kind!r}.")
    if kind in ("person", "org") and not claim:
        raise StageError("Say what they claimed or sold (one line), so the research knows what to check.")
    if kind == "story":
        if db.one("SELECT 1 FROM arc WHERE lower(title)=lower(?)", (name,)):
            raise StageError(f"There's already a topic called '{name}'. Search for it on the Stories tab.")
        arc_id = _new_id("A", "arc", "arc_id", name)
        db.execute("INSERT INTO arc (arc_id, title, status, notes) VALUES (?,?, 'backlog', ?)",
                   (arc_id, name, about or None))
        cid = _claim(claim or name, about, year, arc_id)
        _link_people(cid, people)
        subject = arc_id
        if careful:
            db.execute("INSERT OR IGNORE INTO content_restriction (subject_type, subject_id, rule, note) "
                       "VALUES ('arc', ?, 'courts_only', 'marked careful when added')", (arc_id,))
    elif kind == "conspiracy":
        cid = _claim(name, about or claim, year, None)
        _link_people(cid, people)
        subject = cid
    elif kind == "person":
        pid = _find("person", "person_id", name)
        if not pid:
            pid = _new_id("P", "person", "person_id", name)
            db.execute("INSERT INTO person (person_id, name, role_types, motive_notes, notes) VALUES (?,?,?,?,?)",
                       (pid, name, "said_it", about or None, "added in the Studio"))
        cid = _claim(claim, about, year, None)
        db.execute("INSERT OR IGNORE INTO claim_entity (claim_id, entity_type, entity_id, link_role) VALUES (?,?,?,?)",
                   (cid, "person", pid, "said_it"))
        _link_people(cid, people)
        subject = pid
    else:
        oid = _find("organization", "org_id", name)
        if not oid:
            oid = _new_id("O", "organization", "org_id", name)
            db.execute("INSERT INTO organization (org_id, name, role, notes) VALUES (?,?,?,?)",
                       (oid, name, about or None, "added in the Studio"))
        cid = _claim(claim, about, year, None)
        db.execute("INSERT OR IGNORE INTO claim_entity (claim_id, entity_type, entity_id, link_role) VALUES (?,?,?,?)",
                   (cid, "org", oid, "said_it"))
        _link_people(cid, people)
        subject = oid
    if careful and kind != "story":
        db.execute("INSERT OR IGNORE INTO content_restriction (subject_type, subject_id, rule, note) "
                   "VALUES ('claim', ?, 'courts_only', 'marked careful when added')", (cid,))
    return {"kind": kind, "id": subject, "claim_id": cid}
