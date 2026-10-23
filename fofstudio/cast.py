"""The cast for caricature styles: public figures who SOLD a lie, drawn as clearly-cartoon caricatures.

Guardrails (from the research report "Creative styles and studio polish"; not legal advice):
- Only people linked to this video's ticked claims as the ones who said, amplified, platformed or
  profited from them. Never victims, targets, families, believers or private people.
- Never on careful topics (victims: courts and documents only).
- A fixed written design per person (hair, glasses, build, clothes, props) that YOU approve once.
  Prompts use the design, never the name, so the picture model draws a cartoon, not a photo likeness.
- Cartoon styles only (no photographic style), labelled on screen with "Caricature: <name>" and
  "AI illustration", and only in scenes that cite the documented act they're shown doing.
- No speech bubbles: the only words put in their mouths are verified quotes, shown as quote cards.
"""

from __future__ import annotations

import json
from typing import Any

from . import db
from .episode import Episode
from .util import utc_now

SELLER_ROLES = ("said_it", "amplified", "benefited", "platformed")
NEVER = ("victim", "target", "family", "families", "attorney", "ex-wife", "wife", "husband", "child", "student",
         "private", "parent", "survivor", "witness")
DESIGN_SCHEMA = {"type": "object", "properties": {"design": {"type": "string"}}, "required": ["design"]}


def _never(p: dict[str, Any]) -> bool:
    text = f"{p.get('role_types') or ''}".lower()
    return any(w in text for w in NEVER)


def eligible(ep: Episode, claim_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """People who may be caricatured in this episode, with their design if one exists."""
    from .stages.script import selected_packet
    if claim_ids is None:
        claim_ids = [c["claim_id"] for c in selected_packet(ep)["claims"]]
    if not claim_ids or ep.creative()["careful"]:
        return []
    marks = ",".join("?" * len(claim_ids))
    roles = ",".join("?" * len(SELLER_ROLES))
    rows = db.rows(f"""SELECT p.person_id, p.name, p.role_types, p.status, GROUP_CONCAT(DISTINCT ce.claim_id) AS claims,
                              GROUP_CONCAT(DISTINCT ce.link_role) AS roles
                       FROM claim_entity ce JOIN person p ON p.person_id = ce.entity_id
                       WHERE ce.entity_type='person' AND ce.claim_id IN ({marks}) AND ce.link_role IN ({roles})
                       GROUP BY p.person_id ORDER BY COUNT(*) DESC, p.name""",
                   (*claim_ids, *SELLER_ROLES))
    out = []
    for r in rows:
        if _never(r):
            continue
        d = db.one("SELECT design, approved FROM caricature WHERE person_id=?", (r["person_id"],)) or {}
        out.append({**r, "claims": (r["claims"] or "").split(","), "design": d.get("design") or "",
                    "approved": bool(d.get("approved")), "deceased": (r.get("status") or "") == "deceased"})
    return out


def approved(ep: Episode, claim_ids: list[str] | None = None) -> list[dict[str, Any]]:
    return [p for p in eligible(ep, claim_ids) if p["approved"] and p["design"]]


def save(person_id: str, design: str, ok: bool) -> None:
    db.execute("""INSERT INTO caricature(person_id, design, approved, approved_at) VALUES (?,?,?,?)
                  ON CONFLICT(person_id) DO UPDATE SET design=excluded.design, approved=excluded.approved,
                  approved_at=excluded.approved_at""",
               (person_id, design.strip(), int(ok), utc_now() if ok else None))


def propose(person: dict[str, Any]) -> str:
    """Ask the local AI for a cartoon design from well-known public traits (you edit and approve it)."""
    from .llm import Ollama
    ans = Ollama().chat_json([
        {"role": "system", "content": (
            "You design editorial-cartoon caricatures of public figures for a satire segment. Describe the "
            "cartoon in one or two sentences using only widely known, public visual traits: hair, facial hair, "
            "glasses, build, typical clothing, a signature prop or setting from their public work. Exaggerate "
            "for comedy (big head, small body). Never write the person's name, never describe a photograph, "
            "nothing sexual, nothing about race or ethnicity, nothing demeaning about the body beyond "
            "classic caricature exaggeration.")},
        {"role": "user", "content": f"Public figure: {person['name']} ({person.get('role_types') or ''}). "
                                    "Write the cartoon design."},
    ], DESIGN_SCHEMA, temperature=0.5)
    return (ans.get("design") or "").strip()


def names(ep: Episode) -> dict[str, str]:
    return {p["person_id"]: p["name"] for p in eligible(ep)}


def as_prompt(ep: Episode) -> str:
    return json.dumps([{"person_id": p["person_id"], "who": p.get("role_types"), "design": p["design"]}
                       for p in approved(ep)], ensure_ascii=False)
