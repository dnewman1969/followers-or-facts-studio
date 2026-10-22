"""Consistency checks for the research database (port of truth-vlog's validator).

SQLite's CHECK and FOREIGN KEY rules already stop the worst damage. These
checks catch what the schema can't: links that point at nothing, garbled text,
and claims marked "researched" that have no primary source behind them.
"""

from __future__ import annotations

from pathlib import Path

from .. import db

MOJIBAKE = ["Ã¢â‚¬", "â€™", "â€œ", "â€“", "â€”", "Ã¢", "Â "]


def validate(path: Path | None = None) -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    dangling = db.rows(
        """SELECT ce.claim_id, ce.entity_type, ce.entity_id FROM claim_entity ce
           WHERE (ce.entity_type='person' AND ce.entity_id NOT IN (SELECT person_id FROM person))
              OR (ce.entity_type='org' AND ce.entity_id NOT IN (SELECT org_id FROM organization))
              OR (ce.entity_type='country' AND ce.entity_id NOT IN (SELECT country_id FROM country))""",
        path=path)
    for r in dangling:
        errors.append(f"{r['claim_id']} links to missing {r['entity_type']} {r['entity_id']}")

    for r in db.rows("""SELECT kf_ep, entity_type, entity_id FROM kf_episode_link l
                        WHERE (entity_type='claim' AND entity_id NOT IN (SELECT claim_id FROM claim))
                           OR (entity_type='person' AND entity_id NOT IN (SELECT person_id FROM person))
                           OR (entity_type='org' AND entity_id NOT IN (SELECT org_id FROM organization))
                           OR (entity_type='country' AND entity_id NOT IN (SELECT country_id FROM country))""",
                     path=path):
        warnings.append(f"KF #{r['kf_ep']} links to missing {r['entity_type']} {r['entity_id']}")

    for r in db.rows("""SELECT claim_id FROM claim_readiness
                        WHERE status IN ('researched','video_ready') AND primary_sources = 0""", path=path):
        warnings.append(f"{r['claim_id']} is marked researched but has no primary source")

    for r in db.rows("""SELECT source_id FROM source
                        WHERE is_primary = 1 AND (url IS NULL OR url = '')""", path=path):
        warnings.append(f"{r['source_id']} is a primary source with no URL (can't be fetched or checked)")

    for table, key, cols in (("claim", "claim_id", ("short_title", "claim_summary")),
                             ("source", "source_id", ("title",)),
                             ("person", "person_id", ("name", "notes"))):
        for r in db.rows(f"SELECT {key} AS id, {', '.join(cols)} FROM {table}", path=path):
            text = " ".join(str(r[c] or "") for c in cols)
            if any(m in text for m in MOJIBAKE):
                errors.append(f"{r['id']}: garbled characters (encoding damage)")

    return {"errors": errors, "warnings": warnings}
